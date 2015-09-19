from setuptools import setup, find_packages

setup(
    name='TinyQuery',
    version='0.1.dev1',
    description='A Python in-memory test stub for BigQuery',
    url='https://github.com/burnhamup/tinyquery',
    author='Chris Burnham',
    author_email='chris@burnhamup.com',
    license='MIT',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers,'
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 2.7',
        'Topic :: Software Development :: Testing',
        'Topic :: Database'
    ],
    keywords='bigquery development',
    packages=find_packages(exclude=['tests']),
    install_requires=['ply'],
)