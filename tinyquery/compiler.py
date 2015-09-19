"""The compiler step turns an AST into a planned query.

This step has a number of responsibilities:
-Validate that the expression is well-typed.
-Resolve all select fields to their aliases and types.
"""
import collections

import tinyquery
import parser
import runtime
import tq_ast
import typed_ast
import type_context
import tq_types


class CompileError(Exception):
    pass


def compile_text(text, tables_by_name):
    ast = parser.parse_text(text)
    return Compiler(tables_by_name).compile_select(ast)


class Compiler(object):
    def __init__(self, tables_by_name):
        self.tables_by_name = tables_by_name

    def compile_select(self, select):
        assert isinstance(select, tq_ast.Select)
        table_expr = self.compile_table_expr(select.table_expr)
        table_ctx = table_expr.type_ctx
        where_expr = self.compile_where_expr(select.where_expr, table_ctx)
        select_fields = self.expand_select_fields(select.select_fields,
                                                  table_expr)
        aliases = self.get_aliases(select_fields)
        group_set = self.compile_groups(select.groups, select_fields, aliases,
                                        table_ctx)

        compiled_field_dict, aggregate_context = self.compile_group_fields(
            select_fields, aliases, group_set, table_ctx)

        # Implicit columns can only show up in non-aggregate select fields.
        implicit_column_context = self.find_used_column_context(
            compiled_field_dict.values())

        for alias, select_field in zip(aliases, select_fields):
            if group_set is not None and alias not in group_set.alias_groups:
                compiled_field_dict[alias] = self.compile_select_field(
                    select_field.expr, alias, aggregate_context)

        # Put the compiled select fields in the proper order.
        select_fields = [compiled_field_dict[alias] for alias in aliases]
        result_context = type_context.TypeContext.from_table_and_columns(
            None,
            collections.OrderedDict(
                (field.alias, field.expr.type) for field in select_fields),
            implicit_column_context=implicit_column_context)
        return typed_ast.Select(select_fields, table_expr, where_expr,
                                group_set, select.limit, result_context)

    def expand_select_fields(self, select_fields, table_expr):
        """Expand any stars into a list of all context columns.

        Arguments:
            select_fields: A list of uncompiled select fields, some of which
                can be tq_ast.Star.
            table_expr: The compiled table expression to reference, if
                necessary.
        """
        table_ctx = table_expr.type_ctx
        star_select_fields = []
        for table_name, col_name in table_ctx.columns.iterkeys():
            if table_name is not None:
                col_ref = table_name + '.' + col_name
            else:
                col_ref = col_name
            # Joins are special: the aliases default to a fully-qualified name.
            if isinstance(table_expr, typed_ast.Join):
                alias = table_name + '.' + col_name
            else:
                alias = col_name
            star_select_fields.append(
                tq_ast.SelectField(tq_ast.ColumnId(col_ref), alias))
        result_fields = []
        for field in select_fields:
            if isinstance(field, tq_ast.Star):
                result_fields.extend(star_select_fields)
            else:
                result_fields.append(field)
        return result_fields

    def compile_group_fields(self, select_fields, aliases, group_set,
                             table_ctx):
        """Compile grouped select fields and compute a type context to use.

        Arguments:
            select_fields: A list of uncompiled select fields.
            aliases: A list of aliases that matches with select_fields.
            group_set: A GroupSet for the groups to use.
            table_ctx: A type context for the table being selected.

        Returns:
            compiled_field_dict: An OrderedDict from alias to compiled select
                field for the grouped-by select fields. We use an OrderedDict
                so the order is predictable to make testing easier.
            aggregate_context: A type context that can be used when evaluating
                aggregate select fields.
        """
        compiled_field_dict = collections.OrderedDict()

        group_columns = collections.OrderedDict()

        if group_set is not None:
            for field_group in group_set.field_groups:
                group_columns[
                    (field_group.table, field_group.column)] = field_group.type

        for alias, select_field in zip(aliases, select_fields):
            if group_set is None or alias in group_set.alias_groups:
                compiled_field_dict[alias] = self.compile_select_field(
                    select_field.expr, alias, table_ctx)
                group_columns[
                    (None, alias)] = compiled_field_dict[alias].expr.type

        aggregate_context = type_context.TypeContext.from_full_columns(
            group_columns, aggregate_context=table_ctx)
        return compiled_field_dict, aggregate_context

    def find_used_column_context(self, select_field_list):
        """Given a list of compiled SelectFields, find the used columns.

        The return value is a TypeContext for the columns accessed, so that
        these columns can be used in outer selects, but at lower precedence
        than normal select fields.

        This may also be used in the future to determine which fields to
        actually take from the table.
        """
        column_references = collections.OrderedDict()
        for select_field in select_field_list:
            column_references.update(
                self.find_column_references(select_field.expr))
        return type_context.TypeContext.from_full_columns(column_references)

    def find_column_references(self, expr):
        """Return an OrderedDict of (table, column) -> type."""
        if (isinstance(expr, typed_ast.FunctionCall) or
                isinstance(expr, typed_ast.AggregateFunctionCall)):
            result = collections.OrderedDict()
            for arg in expr.args:
                result.update(self.find_column_references(arg))
            return result
        elif isinstance(expr, typed_ast.ColumnRef):
            return collections.OrderedDict(
                [((expr.table, expr.column), expr.type)])
        elif isinstance(expr, typed_ast.Literal):
            return collections.OrderedDict()
        else:
            assert False, 'Unexpected type: %s' % type(expr)

    def compile_table_expr(self, table_expr):
        """Compile a table expression and determine its result type context.

        Arguments:
            table_expr: Either None (indicating that there no table being
                selected or a TableId.

        Returns: A typed_ast.TableExpression.
        """
        if table_expr is None:
            return typed_ast.NoTable()
        else:
            try:
                method = getattr(self, 'compile_table_expr_' +
                                 table_expr.__class__.__name__)
            except AttributeError:
                raise NotImplementedError('Missing handler for type {}'.format(
                    table_expr.__class__.__name__
                ))
            return method(table_expr)

    def compile_table_expr_TableId(self, table_expr):
        table = self.tables_by_name[table_expr.name]
        if isinstance(table, tinyquery.Table):
            return self.compile_table_ref(table_expr, table)
        elif isinstance(table, tinyquery.View):
            return self.compile_view_ref(table_expr, table)
        else:
            raise NotImplementedError('Unknown table type %s.' % type(table))

    def compile_table_ref(self, table_expr, table):
        alias = table_expr.alias or table_expr.name
        columns = collections.OrderedDict([
            (name, column.type) for name, column in table.columns.iteritems()
        ])
        type_ctx = type_context.TypeContext.from_table_and_columns(
            alias, columns, None)
        return typed_ast.Table(table_expr.name, type_ctx)

    def compile_view_ref(self, table_expr, view):
        # TODO(alan): This code allows fields from the view's implicit column
        # context to be selected, which probably isn't allowed in regular
        # BigQuery.

        # TODO(alan): We should check for cycles when evaluating views.
        # Otherwise, circular views will cause an infinite loop.

        # The view keeps its query as regular text, so we need to lex and parse
        # it, then include it as if it was a subquery. It's almost correct to
        # re-use the subquery compiling code, except that subquery aliases have
        # special semantics that we don't want to use; an alias on a view
        # should count for all returned fields.
        alias = table_expr.alias or table_expr.name
        uncompiled_view_ast = parser.parse_text(view.query)
        compiled_view_select = self.compile_select(uncompiled_view_ast)
        # We always want to apply either the alias or the full table name to
        # the returned type context.
        new_type_context = (
            compiled_view_select.type_ctx.context_with_full_alias(alias))
        return compiled_view_select.with_type_ctx(new_type_context)

    def compile_table_expr_TableUnion(self, table_expr):
        compiled_tables = [
            self.compile_table_expr(table) for table in table_expr.tables]
        type_ctx = type_context.TypeContext.union_contexts(
            table.type_ctx for table in compiled_tables)
        return typed_ast.TableUnion(compiled_tables, type_ctx)

    def compile_table_expr_CrossJoin(self, table_expr):
        compiled_table1, _ = self.compile_joined_table(table_expr.table1)
        compiled_table2, _ = self.compile_joined_table(table_expr.table2)
        result_type_ctx = type_context.TypeContext.join_contexts(
            [compiled_table1.type_ctx, compiled_table2.type_ctx])
        return typed_ast.Join(compiled_table1, compiled_table2, [],
                              False, result_type_ctx)

    def compile_table_expr_Join(self, table_expr):
        compiled_table1, alias1 = self.compile_joined_table(table_expr.table1)
        compiled_table2, alias2 = self.compile_joined_table(table_expr.table2)
        result_fields = self.compile_join_fields(
            compiled_table1.type_ctx, compiled_table2.type_ctx, alias1, alias2,
            table_expr.condition)
        result_type_ctx = type_context.TypeContext.join_contexts(
            [compiled_table1.type_ctx, compiled_table2.type_ctx])
        return typed_ast.Join(compiled_table1, compiled_table2, result_fields,
                              table_expr.is_left_outer, result_type_ctx)

    def compile_joined_table(self, table_expr):
        """Given one side of a JOIN, get its table expression and alias."""
        compiled_table = self.compile_table_expr(table_expr)
        if table_expr.alias is not None:
            alias = table_expr.alias
        elif isinstance(table_expr, tq_ast.TableId):
            alias = table_expr.name
        else:
            raise CompileError('Table expression must have an alias name.')
        result_ctx = compiled_table.type_ctx.context_with_full_alias(alias)
        compiled_table = compiled_table.with_type_ctx(result_ctx)
        return compiled_table, alias

    def compile_join_fields(self, type_ctx1, type_ctx2, alias1, alias2, expr):
        """Traverse a join condition to find the joined fields.

        Arguments:
            type_ctx1: A TypeContext for the first table being joined.
            type_ctx2: A TypeContext for the second table being joined.
            alias1: The alias for the first table.
            alias2: The alias for the second table.
            expr: An uncompiled tq_ast expression to traverse.

        Returns: A list of JoinFields instances for the expression.
        """
        if isinstance(expr, tq_ast.BinaryOperator):
            if expr.operator == 'and':
                return (self.compile_join_fields(
                    type_ctx1, type_ctx2, alias1, alias2, expr.left) +
                    self.compile_join_fields(
                        type_ctx1, type_ctx2, alias1, alias2, expr.right))
            elif (expr.operator == '=' and
                    isinstance(expr.left, tq_ast.ColumnId) and
                    isinstance(expr.right, tq_ast.ColumnId)):
                column_id1, column_id2 = expr.left, expr.right
                # By default, the left side of the equality corresponds to the
                # left side of the join, but this can be overridden if any
                # aliases suggest that the reverse order should be used.
                if (column_id1.name.startswith(alias2 + '.') or
                        column_id2.name.startswith(alias1 + '.')):
                    column_id1, column_id2 = column_id2, column_id1
                column_ref1 = self.compile_ColumnId(column_id1, type_ctx1)
                column_ref2 = self.compile_ColumnId(column_id2, type_ctx2)
                return [typed_ast.JoinFields(column_ref1, column_ref2)]
        raise CompileError('JOIN conditions must consist of an AND of = '
                           'comparisons. Got expression {}'.format(expr))

    def compile_table_expr_Select(self, table_expr):
        select_result = self.compile_select(table_expr)
        if table_expr.alias is not None:
            new_type_context = (select_result.type_ctx.
                                context_with_subquery_alias(table_expr.alias))
            select_result = select_result.with_type_ctx(new_type_context)
        return select_result

    def compile_groups(self, groups, select_fields, aliases, table_ctx):
        """Gets the group set to use for the query.

        This involves handling the special cases when no GROUP BY statement
        exists, and also determining whether each group should be treated as an
        alias group or a field group.

        Arguments:
            groups: Either None, indicating that no GROUP BY was specified, or
                a list of strings from the GROUP BY.
            select_fields: A list of tq_ast.SelectField objects for the query
                we are compiling.
            aliases: The aliases we will assign to the select fields.
            table_ctx: The TypeContext from the table expression in the SELECT.
        """
        if groups is None:
            # Special case: if no GROUP BY was specified, we're an aggregate
            # query iff at least one select field has an aggregate function.
            is_aggregate_select = any(
                self.expression_contains_aggregate(field.expr)
                for field in select_fields)

            if is_aggregate_select:
                # Group such that everything is in the same group.
                return typed_ast.TRIVIAL_GROUP_SET
            else:
                # Don't do any grouping at all.
                return None
        else:
            # At least one group was specified, so this is definitely a
            # GROUP BY query and we need to figure out what they refer to.
            alias_groups = set()
            field_groups = []

            alias_set = set(aliases)
            for group in groups:
                if group.name in alias_set:
                    alias_groups.add(group.name)
                else:
                    # Will raise an exception if not found.
                    # TODO: This doesn't perfectly match BigQuery's approach.
                    # In BigQuery, grouping by my_table.my_value will make
                    # either my_table.my_value or my_value valid ways of
                    # referring to the group, whereas grouping by my_value will
                    # make it so only my_value is a valid way of referring to
                    # the group. The whole approach to implicit table
                    # references could potentially be rethought.
                    field_groups.append(
                        table_ctx.column_ref_for_name(group.name))
            return typed_ast.GroupSet(alias_groups, field_groups)

    def compile_select_field(self, expr, alias, type_ctx):
        compiled_expr = self.compile_expr(expr, type_ctx)
        return typed_ast.SelectField(compiled_expr, alias)

    def compile_where_expr(self, where_expr, table_ctx):
        """If there is a WHERE expression, compile it.

        If the WHERE expression is missing, we just use the literal true.
        """
        if where_expr:
            return self.compile_expr(where_expr, table_ctx)
        else:
            return typed_ast.Literal(True, tq_types.BOOL)

    def compile_expr(self, expr, type_ctx):
        try:
            method = getattr(self, 'compile_' + expr.__class__.__name__)
        except AttributeError:
            raise NotImplementedError(
                'Missing handler for type {}'.format(expr.__class__.__name__))
        return method(expr, type_ctx)

    def compile_ColumnId(self, expr, type_ctx):
        return type_ctx.column_ref_for_name(expr.name)

    def compile_Literal(self, expr, type_ctx):
        if isinstance(expr.value, bool):
            return typed_ast.Literal(expr.value, tq_types.BOOL)
        if isinstance(expr.value, int):
            return typed_ast.Literal(expr.value, tq_types.INT)
        if isinstance(expr.value, float):
            return typed_ast.Literal(expr.value, tq_types.FLOAT)
        elif isinstance(expr.value, basestring):
            return typed_ast.Literal(expr.value, tq_types.STRING)
        elif expr.value is None:
            return typed_ast.Literal(expr.value, tq_types.NONETYPE)
        else:
            raise NotImplementedError('Unrecognized type: {}'.format(
                type(expr.value)))

    def compile_UnaryOperator(self, expr, type_ctx):
        func = runtime.get_unary_op(expr.operator)
        compiled_val = self.compile_expr(expr.expr, type_ctx)
        result_type = func.check_types(compiled_val.type)
        return typed_ast.FunctionCall(func, [compiled_val], result_type)

    def compile_BinaryOperator(self, expr, type_ctx):
        func = runtime.get_binary_op(expr.operator)

        compiled_left = self.compile_expr(expr.left, type_ctx)
        compiled_right = self.compile_expr(expr.right, type_ctx)

        result_type = func.check_types(compiled_left.type, compiled_right.type)

        return typed_ast.FunctionCall(
            func, [compiled_left, compiled_right], result_type)

    def compile_FunctionCall(self, expr, type_ctx):
        # Innermost aggregates are special, since the context to use changes
        # inside them. We also need to generate an AggregateFunctionCall AST so
        # that the evaluator knows to change the context.
        if self.is_innermost_aggregate(expr):
            if type_ctx.aggregate_context is None:
                raise CompileError('Unexpected aggregate function.')
            sub_expr_ctx = type_ctx.aggregate_context
            ast_type = typed_ast.AggregateFunctionCall
        else:
            sub_expr_ctx = type_ctx
            ast_type = typed_ast.FunctionCall

        func = runtime.get_func(expr.name)
        compiled_args = [self.compile_expr(sub_expr, sub_expr_ctx)
                         for sub_expr in expr.args]
        try:
            result_type = func.check_types(
                *(arg.type for arg in compiled_args))
        except TypeError:
            raise CompileError('Invalid types for function {}: {}'.format(
                expr.name, [arg.type for arg in compiled_args]))
        return ast_type(func, compiled_args, result_type)

    @classmethod
    def get_aliases(cls, select_field_list):
        """Given a list of tq_ast.SelectField, return the aliases to use."""
        used_aliases = set()
        proposed_aliases = [cls.field_alias(select_field)
                            for select_field in select_field_list]
        for alias in proposed_aliases:
            if alias is not None:
                if alias in used_aliases:
                    raise CompileError(
                        'Ambiguous column name {}.'.format(alias))
                used_aliases.add(alias)

        generic_field_num = 0
        result = []
        for alias in proposed_aliases:
            if alias is not None:
                result.append(alias)
            else:
                while ('f%s_' % generic_field_num) in used_aliases:
                    generic_field_num += 1
                result.append('f%s_' % generic_field_num)
                generic_field_num += 1
        return result

    @staticmethod
    def field_alias(select_field):
        """Gets the alias to use, or None if it's not specified."""
        if select_field.alias is not None:
            return select_field.alias
        if isinstance(select_field.expr, tq_ast.ColumnId):
            return select_field.expr.name
        return None

    @classmethod
    def expression_contains_aggregate(cls, expr):
        """Given a tq_ast expression, check if it does any aggregation.

        We need to operate on an uncompiled AST here since we use this
        information to figure out how to compile these expressions.
        """
        if isinstance(expr, tq_ast.UnaryOperator):
            return cls.expression_contains_aggregate(expr.expr)
        elif isinstance(expr, tq_ast.BinaryOperator):
            return (cls.expression_contains_aggregate(expr.left) or
                    cls.expression_contains_aggregate(expr.right))
        elif isinstance(expr, tq_ast.FunctionCall):
            return (runtime.is_aggregate_func(expr.name) or
                    any(cls.expression_contains_aggregate(arg)
                        for arg in expr.args))
        elif isinstance(expr, tq_ast.Literal):
            return False
        elif isinstance(expr, tq_ast.ColumnId):
            return False
        else:
            assert False, 'Unexpected expression type: %s' % (
                expr.__class__.__name__)

    @classmethod
    def is_innermost_aggregate(cls, expr):
        """Return True if the given expression is an innermost aggregate.

        Only arguments to innermost aggregates actually have access to fields
        from the original table expression, so we need to detect this case
        specifically.

        You might think that repeatedly calling this function while traversing
        the tree takes quadratic time in the size of the tree, but it actually
        only takes linear time overall. There's a nice proof of this fact,
        which this docstring is to small to contain.
        """
        return (isinstance(expr, tq_ast.FunctionCall) and
                runtime.is_aggregate_func(expr.name) and
                not any(cls.expression_contains_aggregate(sub_expr)
                        for sub_expr in expr.args))
