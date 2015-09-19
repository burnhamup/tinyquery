import collections
import unittest

from tinyquery import compiler, context, runtime, tinyquery, tq_types, type_context, typed_ast


class CompilerTest(unittest.TestCase):
    def setUp(self):
        self.table1 = tinyquery.Table(
            'table1',
            0,
            collections.OrderedDict([
                ('value', context.Column(tq_types.INT, [])),
                ('value2', context.Column(tq_types.INT, []))
            ]))
        self.table1_type_ctx = self.make_type_context(
            [('table1', 'value', tq_types.INT),
             ('table1', 'value2', tq_types.INT)]
        )

        self.table2 = tinyquery.Table(
            'table2',
            0,
            collections.OrderedDict([
                ('value', context.Column(tq_types.INT, [])),
                ('value3', context.Column(tq_types.INT, []))
            ])
        )
        self.table2_type_ctx = self.make_type_context(
            [('table2', 'value', tq_types.INT),
             ('table2', 'value3', tq_types.INT)]
        )

        self.tables_by_name = {
            'table1': self.table1,
            'table2': self.table2
        }

    def assert_compiled_select(self, text, expected_ast):
        ast = compiler.compile_text(text, self.tables_by_name)
        self.assertEqual(expected_ast, ast)

    def assert_compile_error(self, text):
        self.assertRaises(compiler.CompileError, compiler.compile_text,
                          text, self.tables_by_name)

    def make_type_context(self, table_column_type_triples,
                          implicit_column_context=None):
        return type_context.TypeContext.from_full_columns(
            collections.OrderedDict(
                ((table, column), col_type)
                for table, column, col_type in table_column_type_triples
            ), implicit_column_context)

    def test_compile_simple_select(self):
        self.assert_compiled_select(
            'SELECT value FROM table1',
            typed_ast.Select(
                [typed_ast.SelectField(
                    typed_ast.ColumnRef('table1', 'value', tq_types.INT),
                    'value')],
                typed_ast.Table('table1', self.table1_type_ctx),
                typed_ast.Literal(True, tq_types.BOOL),
                None,
                None,
                self.make_type_context(
                    [(None, 'value', tq_types.INT)],
                    self.make_type_context([('table1', 'value', tq_types.INT)])
                ))
        )

    def test_unary_operator(self):
        self.assert_compiled_select(
            'SELECT -5',
            typed_ast.Select(
                [typed_ast.SelectField(
                    typed_ast.FunctionCall(
                        runtime.get_unary_op('-'),
                        [typed_ast.Literal(5, tq_types.INT)],
                        tq_types.INT),
                    'f0_'
                )],
                typed_ast.NoTable(),
                typed_ast.Literal(True, tq_types.BOOL),
                None,
                None,
                self.make_type_context(
                    [(None, 'f0_', tq_types.INT)],
                    self.make_type_context([]))
            )
        )

    def test_function_calls(self):
        self.assert_compiled_select(
            'SELECT ABS(-3), POW(2, 3), NOW()',
            typed_ast.Select([
                typed_ast.SelectField(
                    typed_ast.FunctionCall(
                        runtime.get_func('abs'),
                        [typed_ast.FunctionCall(
                            runtime.get_unary_op('-'),
                            [typed_ast.Literal(3, tq_types.INT)],
                            tq_types.INT
                        )],
                        tq_types.INT),
                    'f0_'),
                typed_ast.SelectField(
                    typed_ast.FunctionCall(
                        runtime.get_func('pow'), [
                            typed_ast.Literal(2, tq_types.INT),
                            typed_ast.Literal(3, tq_types.INT)],
                        tq_types.INT
                    ),
                    'f1_'
                ),
                typed_ast.SelectField(
                    typed_ast.FunctionCall(
                        runtime.get_func('now'), [], tq_types.INT
                    ),
                    'f2_'
                )],
                typed_ast.NoTable(),
                typed_ast.Literal(True, tq_types.BOOL),
                None,
                None,
                self.make_type_context([
                    (None, 'f0_', tq_types.INT), (None, 'f1_', tq_types.INT),
                    (None, 'f2_', tq_types.INT)],
                    self.make_type_context([]))
            )
        )

    def test_where(self):
        self.assert_compiled_select(
            'SELECT value FROM table1 WHERE value > 3',
            typed_ast.Select(
                [typed_ast.SelectField(
                    typed_ast.ColumnRef('table1', 'value', tq_types.INT),
                    'value')],
                typed_ast.Table('table1', self.table1_type_ctx),
                typed_ast.FunctionCall(
                    runtime.get_binary_op('>'),
                    [typed_ast.ColumnRef('table1', 'value', tq_types.INT),
                     typed_ast.Literal(3, tq_types.INT)],
                    tq_types.BOOL),
                None,
                None,
                self.make_type_context(
                    [(None, 'value', tq_types.INT)],
                    self.make_type_context(
                        [('table1', 'value', tq_types.INT)]))
            )
        )

    def test_multiple_select(self):
        self.assert_compiled_select(
            'SELECT value * 3 AS foo, value, value + 1, value bar, value - 1 '
            'FROM table1',
            typed_ast.Select(
                [typed_ast.SelectField(
                    typed_ast.FunctionCall(
                        runtime.get_binary_op('*'),
                        [typed_ast.ColumnRef('table1', 'value', tq_types.INT),
                         typed_ast.Literal(3, tq_types.INT)],
                        tq_types.INT),
                    'foo'),
                 typed_ast.SelectField(
                     typed_ast.ColumnRef('table1', 'value', tq_types.INT),
                     'value'),
                 typed_ast.SelectField(
                     typed_ast.FunctionCall(
                         runtime.get_binary_op('+'),
                         [typed_ast.ColumnRef('table1', 'value', tq_types.INT),
                          typed_ast.Literal(1, tq_types.INT)],
                         tq_types.INT),
                     'f0_'),
                 typed_ast.SelectField(
                     typed_ast.ColumnRef('table1', 'value', tq_types.INT),
                     'bar'),
                 typed_ast.SelectField(
                     typed_ast.FunctionCall(
                         runtime.get_binary_op('-'),
                         [typed_ast.ColumnRef('table1', 'value', tq_types.INT),
                          typed_ast.Literal(1, tq_types.INT)],
                         tq_types.INT),
                     'f1_')],
                typed_ast.Table('table1', self.table1_type_ctx),
                typed_ast.Literal(True, tq_types.BOOL),
                None,
                None,
                self.make_type_context([
                    (None, 'foo', tq_types.INT),
                    (None, 'value', tq_types.INT),
                    (None, 'f0_', tq_types.INT), (None, 'bar', tq_types.INT),
                    (None, 'f1_', tq_types.INT)],
                    self.make_type_context(
                        [('table1', 'value', tq_types.INT)]
                    ))
            )
        )

    def test_duplicate_aliases_not_allowed(self):
        self.assert_compile_error(
            'SELECT 0 AS foo, value foo FROM table1')

    def test_aggregates(self):
        self.assert_compiled_select(
            'SELECT MAX(value), MIN(value) FROM table1',
            typed_ast.Select([
                typed_ast.SelectField(
                    typed_ast.AggregateFunctionCall(
                        runtime.get_func('max'),
                        [typed_ast.ColumnRef('table1', 'value', tq_types.INT)],
                        tq_types.INT
                    ),
                    'f0_'),
                typed_ast.SelectField(
                    typed_ast.AggregateFunctionCall(
                        runtime.get_func('min'),
                        [typed_ast.ColumnRef('table1', 'value', tq_types.INT)],
                        tq_types.INT
                    ),
                    'f1_')],
                typed_ast.Table('table1', self.table1_type_ctx),
                typed_ast.Literal(True, tq_types.BOOL),
                typed_ast.GroupSet(set(), []),
                None,
                self.make_type_context([
                    (None, 'f0_', tq_types.INT),
                    (None, 'f1_', tq_types.INT)],
                    self.make_type_context([]))))

    def mixed_aggregate_non_aggregate_not_allowed(self):
        self.assert_compile_error(
            'SELECT value, SUM(value) FROM table1')

    def mixed_aggregate_non_aggregate_single_field_not_allowed(self):
        self.assert_compile_error(
            'SELECT value + SUM(value) FROM table1')

    def test_group_by_alias(self):
        self.assert_compiled_select(
            'SELECT 0 AS foo FROM table1 GROUP BY foo',
            typed_ast.Select(
                [typed_ast.SelectField(
                    typed_ast.Literal(0, tq_types.INT), 'foo')],
                typed_ast.Table('table1', self.table1_type_ctx),
                typed_ast.Literal(True, tq_types.BOOL),
                typed_ast.GroupSet(
                    alias_groups={'foo'},
                    field_groups=[]
                ),
                None,
                self.make_type_context(
                    [(None, 'foo', tq_types.INT)],
                    self.make_type_context([]))
            )
        )

    def test_group_by_field(self):
        self.assert_compiled_select(
            'SELECT SUM(value) FROM table1 GROUP BY value2',
            typed_ast.Select(
                [typed_ast.SelectField(
                    typed_ast.FunctionCall(
                        runtime.get_func('sum'),
                        [typed_ast.ColumnRef('table1', 'value', tq_types.INT)],
                        tq_types.INT
                    ),
                    'f0_')],
                typed_ast.Table('table1', self.table1_type_ctx),
                typed_ast.Literal(True, tq_types.BOOL),
                typed_ast.GroupSet(
                    alias_groups=set(),
                    field_groups=[
                        typed_ast.ColumnRef('table1', 'value2', tq_types.INT)]
                ),
                None,
                self.make_type_context(
                    [(None, 'f0_', tq_types.INT)],
                    self.make_type_context([]))
            ))

    def test_select_grouped_and_non_grouped_fields(self):
        self.assert_compiled_select(
            'SELECT value, SUM(value2) FROM table1 GROUP BY value',
            typed_ast.Select([
                typed_ast.SelectField(
                    typed_ast.ColumnRef('table1', 'value', tq_types.INT),
                    'value'),
                typed_ast.SelectField(
                    typed_ast.FunctionCall(
                        runtime.get_func('sum'),
                        [typed_ast.ColumnRef('table1', 'value2',
                                             tq_types.INT)],
                        tq_types.INT),
                    'f0_')],
                typed_ast.Table('table1', self.table1_type_ctx),
                typed_ast.Literal(True, tq_types.BOOL),
                typed_ast.GroupSet(
                    alias_groups={'value'},
                    field_groups=[]
                ),
                None,
                self.make_type_context(
                    [(None, 'value', tq_types.INT),
                     (None, 'f0_', tq_types.INT)],
                    self.make_type_context(
                        [('table1', 'value', tq_types.INT)]))
            )
        )

    def test_grouped_fields_require_aggregates(self):
        self.assert_compile_error(
            'SELECT value + 1 AS foo, foo FROM table1 GROUP BY foo')

    def test_select_multiple_tables(self):
        # Union of columns should be taken, with no aliases.
        unioned_type_ctx = self.make_type_context(
            [(None, 'value', tq_types.INT), (None, 'value2', tq_types.INT),
             (None, 'value3', tq_types.INT)])

        self.assert_compiled_select(
            'SELECT value, value2, value3 FROM table1, table2',
            typed_ast.Select([
                typed_ast.SelectField(
                    typed_ast.ColumnRef(None, 'value', tq_types.INT),
                    'value'),
                typed_ast.SelectField(
                    typed_ast.ColumnRef(None, 'value2', tq_types.INT),
                    'value2'),
                typed_ast.SelectField(
                    typed_ast.ColumnRef(None, 'value3', tq_types.INT),
                    'value3')],
                typed_ast.TableUnion([
                    typed_ast.Table('table1', self.table1_type_ctx),
                    typed_ast.Table('table2', self.table2_type_ctx)],
                    unioned_type_ctx
                ),
                typed_ast.Literal(True, tq_types.BOOL),
                None,
                None,
                self.make_type_context(
                    [(None, 'value', tq_types.INT),
                     (None, 'value2', tq_types.INT),
                     (None, 'value3', tq_types.INT)],
                    self.make_type_context(
                        [(None, 'value', tq_types.INT),
                         (None, 'value2', tq_types.INT),
                         (None, 'value3', tq_types.INT)]))
            )
        )

    def test_subquery(self):
        self.assert_compiled_select(
            'SELECT foo, foo + 1 FROM (SELECT value + 1 AS foo FROM table1)',
            typed_ast.Select([
                typed_ast.SelectField(
                    typed_ast.ColumnRef(None, 'foo', tq_types.INT), 'foo'),
                typed_ast.SelectField(
                    typed_ast.FunctionCall(
                        runtime.get_binary_op('+'), [
                            typed_ast.ColumnRef(None, 'foo', tq_types.INT),
                            typed_ast.Literal(1, tq_types.INT)],
                        tq_types.INT),
                    'f0_'
                )],
                typed_ast.Select(
                    [typed_ast.SelectField(
                        typed_ast.FunctionCall(
                            runtime.get_binary_op('+'), [
                                typed_ast.ColumnRef('table1', 'value',
                                                    tq_types.INT),
                                typed_ast.Literal(1, tq_types.INT)],
                            tq_types.INT),
                        'foo'
                    )],
                    typed_ast.Table('table1', self.table1_type_ctx),
                    typed_ast.Literal(True, tq_types.BOOL),
                    None,
                    None,
                    self.make_type_context(
                        [(None, 'foo', tq_types.INT)],
                        self.make_type_context(
                            [('table1', 'value', tq_types.INT)]
                        ))
                ),
                typed_ast.Literal(True, tq_types.BOOL),
                None,
                None,
                self.make_type_context(
                    [(None, 'foo', tq_types.INT), (None, 'f0_', tq_types.INT)],
                    self.make_type_context([(None, 'foo', tq_types.INT)]))
            )
        )

    def test_table_aliases(self):
        self.assert_compiled_select(
            'SELECT t.value FROM table1 t',
            typed_ast.Select([
                typed_ast.SelectField(
                    typed_ast.ColumnRef('t', 'value', tq_types.INT),
                    't.value')],
                typed_ast.Table('table1', self.make_type_context(
                    [('t', 'value', tq_types.INT),
                     ('t', 'value2', tq_types.INT)])),
                typed_ast.Literal(True, tq_types.BOOL),
                None,
                None,
                self.make_type_context(
                    [(None, 't.value', tq_types.INT)],
                    self.make_type_context(
                        [('t', 'value', tq_types.INT)]
                    ))
            )
        )

    def test_implicitly_accessed_column(self):
        self.assert_compiled_select(
            'SELECT table1.value FROM (SELECT value + 1 AS foo FROM table1)',
            typed_ast.Select([
                typed_ast.SelectField(
                    typed_ast.ColumnRef('table1', 'value', tq_types.INT),
                    'table1.value')],
                typed_ast.Select([
                    typed_ast.SelectField(
                        typed_ast.FunctionCall(
                            runtime.get_binary_op('+'), [
                                typed_ast.ColumnRef('table1', 'value',
                                                    tq_types.INT),
                                typed_ast.Literal(1, tq_types.INT)
                            ],
                            tq_types.INT
                        ),
                        'foo')],
                    typed_ast.Table('table1', self.table1_type_ctx),
                    typed_ast.Literal(True, tq_types.BOOL),
                    None,
                    None,
                    self.make_type_context(
                        [(None, 'foo', tq_types.INT)],
                        self.make_type_context(
                            [('table1', 'value', tq_types.INT)]))),
                typed_ast.Literal(True, tq_types.BOOL),
                None,
                None,
                self.make_type_context(
                    [(None, 'table1.value', tq_types.INT)],
                    self.make_type_context(
                        [('table1', 'value', tq_types.INT)]
                    )))
        )

    def test_subquery_aliases(self):
        self.assert_compiled_select(
            'SELECT t.value FROM (SELECT value FROM table1) t',
            typed_ast.Select([
                typed_ast.SelectField(
                    typed_ast.ColumnRef('t', 'value', tq_types.INT),
                    't.value')],
                typed_ast.Select([
                    typed_ast.SelectField(
                        typed_ast.ColumnRef('table1', 'value', tq_types.INT),
                        'value')],
                    typed_ast.Table('table1', self.table1_type_ctx),
                    typed_ast.Literal(True, tq_types.BOOL),
                    None,
                    None,
                    self.make_type_context(
                        [(None, 'value', tq_types.INT)],
                        self.make_type_context(
                            [('t', 'value', tq_types.INT)]))
                ),
                typed_ast.Literal(True, tq_types.BOOL),
                None,
                None,
                self.make_type_context(
                    [(None, 't.value', tq_types.INT)],
                    self.make_type_context(
                        [('t', 'value', tq_types.INT)]))
            )
        )

    def test_simple_join(self):
        self.assert_compiled_select(
            'SELECT value2 '
            'FROM table1 t1 JOIN table2 t2 ON t1.value = t2.value',
            typed_ast.Select([
                typed_ast.SelectField(
                    typed_ast.ColumnRef('t1', 'value2', tq_types.INT),
                    'value2'
                )],
                typed_ast.Join(
                    typed_ast.Table('table1',
                                    self.make_type_context([
                                        ('t1', 'value', tq_types.INT),
                                        ('t1', 'value2', tq_types.INT),
                                    ])),
                    typed_ast.Table('table2',
                                    self.make_type_context([
                                        ('t2', 'value', tq_types.INT),
                                        ('t2', 'value3', tq_types.INT),
                                    ])),
                    [typed_ast.JoinFields(
                        typed_ast.ColumnRef('t1', 'value', tq_types.INT),
                        typed_ast.ColumnRef('t2', 'value', tq_types.INT)
                    )],
                    False,
                    self.make_type_context([
                        ('t1', 'value', tq_types.INT),
                        ('t1', 'value2', tq_types.INT),
                        ('t2', 'value', tq_types.INT),
                        ('t2', 'value3', tq_types.INT),
                    ])
                ),
                typed_ast.Literal(True, tq_types.BOOL),
                None,
                None,
                self.make_type_context(
                    [(None, 'value2', tq_types.INT)],
                    self.make_type_context([('t1', 'value2', tq_types.INT)])
                )
            )
        )

    def test_join_multiple_fields(self):
        self.assert_compiled_select(
            'SELECT 0 '
            'FROM table1 t1 JOIN table2 t2 '
            'ON t1.value = t2.value AND t2.value3 = t1.value2',
            typed_ast.Select(
                [typed_ast.SelectField(
                    typed_ast.Literal(0, tq_types.INT), 'f0_')],
                typed_ast.Join(
                    typed_ast.Table('table1',
                                    self.make_type_context([
                                        ('t1', 'value', tq_types.INT),
                                        ('t1', 'value2', tq_types.INT),
                                    ])),
                    typed_ast.Table('table2',
                                    self.make_type_context([
                                        ('t2', 'value', tq_types.INT),
                                        ('t2', 'value3', tq_types.INT),
                                    ])),
                    [typed_ast.JoinFields(
                        typed_ast.ColumnRef('t1', 'value', tq_types.INT),
                        typed_ast.ColumnRef('t2', 'value', tq_types.INT)
                    ), typed_ast.JoinFields(
                        typed_ast.ColumnRef('t1', 'value2', tq_types.INT),
                        typed_ast.ColumnRef('t2', 'value3', tq_types.INT)
                    )],
                    False,
                    self.make_type_context([
                        ('t1', 'value', tq_types.INT),
                        ('t1', 'value2', tq_types.INT),
                        ('t2', 'value', tq_types.INT),
                        ('t2', 'value3', tq_types.INT),
                    ])
                ),
                typed_ast.Literal(True, tq_types.BOOL),
                None,
                None,
                self.make_type_context(
                    [(None, 'f0_', tq_types.INT)],
                    self.make_type_context([]))
            )
        )

    def test_select_star(self):
        self.assert_compiled_select(
            'SELECT * FROM table1',
            typed_ast.Select([
                typed_ast.SelectField(
                    typed_ast.ColumnRef('table1', 'value', tq_types.INT),
                    'value'),
                typed_ast.SelectField(
                    typed_ast.ColumnRef('table1', 'value2', tq_types.INT),
                    'value2')],
                typed_ast.Table('table1', self.table1_type_ctx),
                typed_ast.Literal(True, tq_types.BOOL),
                None,
                None,
                self.make_type_context([
                    (None, 'value', tq_types.INT),
                    (None, 'value2', tq_types.INT)],
                    self.make_type_context([
                        ('table1', 'value', tq_types.INT),
                        ('table1', 'value2', tq_types.INT)]))))
