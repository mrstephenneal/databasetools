import os
import mysql.connector
from mysql.connector import errorcode
from tqdm import tqdm
from databasetools.sqlprep import prepare_sql


def get_column_value_strings(columns, query_type='insert'):
    cols = ""
    vals = ""
    if query_type == 'insert':
        for c in columns:
            cols = cols + c + ', '
            vals = vals + '%s' + ', '

        # Remove last comma and space
        cols = cols[:-2]
        vals = vals[:-2]
        return cols, vals
    if query_type == 'update':
        for c in columns:
            cols = str(cols + c + '=%s, ')

        # Remove last comma and space
        cols = cols[:-2]
        return cols


def join_columns(cols):
    """Join list of columns into a string for a SQL query"""
    return ", ".join([i for i in cols]) if isinstance(cols, list) else cols


def differentiate(x, y):
    """
    Retrieve a unique of list of elements that do not exist in both x and y.
    Capable of parsing one-dimensional (flat) and two-dimensional (lists of lists) lists.

    :param x: list #1
    :param y: list #2
    :return: list of unique values
    """
    # Validate both lists, confirm either are empty
    if len(x) == 0 and len(y) > 0:
        return y  # All y values are unique if x is empty
    elif len(y) == 0 and len(x) > 0:
        return x  # All x values are unique if y is empty

    # Get the input type to convert back to before return
    try:
        input_type = type(x[0])
    except IndexError:
        input_type = type(y[0])

    # Dealing with a 2D dataset (list of lists)
    try:
        # Immutable and Unique - Convert list of tuples into set of tuples
        first_set = set(map(tuple, x))
        secnd_set = set(map(tuple, y))

    # Dealing with a 1D dataset (list of items)
    except TypeError:
        # Unique values only
        first_set = set(x)
        secnd_set = set(y)

    # Determine which list is longest
    longest = first_set if len(first_set) > len(secnd_set) else secnd_set
    shortest = secnd_set if len(first_set) > len(secnd_set) else first_set

    # Generate set of non-shared values and return list of values in original type
    return [input_type(i) for i in {i for i in longest if i not in shortest}]


class MySQL:
    def __init__(self, config, enable_printing=True):
        """
        Connect to MySQL database and execute queries
        :param config: MySQL server configuration settings
        """
        self.enable_printing = enable_printing
        self._cursor = None
        self._cnx = None
        self._connect(config)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._commit()
        self._close()

    @property
    def tables(self):
        """Retrieve a list of tables in the connected database"""
        statement = 'show tables'
        return self._fetch(statement)

    @property
    def databases(self):
        """Retrieve a list of databases that are accessible under the current connection"""
        return self._fetch('show databases')

    def _connect(self, config):
        """Establish a connection with a MySQL database."""
        try:
            self._cnx = mysql.connector.connect(**config)
            self._cursor = self._cnx.cursor()
            self._printer('\tMySQL DB connection established')
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                print("Something is wrong with your user name or password")
            elif err.errno == errorcode.ER_BAD_DB_ERROR:
                print("Database does not exist")
            raise err

    def _printer(self, *msg):
        """Printing method for internal use."""
        if self.enable_printing:
            print(*msg)

    def _close(self):
        """Close MySQL database connection."""
        self._cursor.close()
        self._cnx.close()

    def _commit(self):
        """Commit the changes made during the current connection."""
        self._cnx.commit()

    def _fetch(self, statement, _print=False):
        """Execute a SQL query and return values."""
        # Execute statement
        self._cursor.execute(statement)
        rows = []
        for row in self._cursor:
            if len(row) == 1:
                rows.append(row[0])
            else:
                rows.append(list(row))
        if _print:
            self._printer('\tMySQL rows successfully queried', len(rows))

        # Return a single item if the list only has one item
        if len(rows) == 1:
            return rows[0]
        else:
            return rows

    def execute(self, command):
        self._cursor.execute(command)
        self._commit()

    def executemany(self, command):
        self._cursor.executemany(command)
        self._commit()

    def select(self, table, cols, _print=True):
        """Query only certain columns from a table and every row."""
        # Concatenate statement
        cols_str = join_columns(cols)
        statement = ("SELECT " + cols_str + " FROM " + str(table))
        return self._fetch(statement, _print)

    def select_where(self, table, cols, where):
        """Query certain columns from a table where a particular value is found."""
        # Either join list of columns into string or set columns to * (all)
        if isinstance(cols, list):
            cols_str = join_columns(cols)
        else:
            cols_str = "*"

        # Unpack WHERE clause dictionary into tuple
        where_col, where_val = where

        statement = ("SELECT " + cols_str + " FROM " + str(table) + ' WHERE ' + str(where_col) + '=' + str(where_val))
        self._fetch(statement)

    def select_all(self, table):
        """Query all rows and columns from a table."""
        # Concatenate statement
        statement = ("SELECT * FROM " + str(table))
        return self._fetch(statement)

    def select_all_join(self, table1, table2, key):
        """Left join all rows and columns from two tables where a common value is shared."""
        # TODO: Write function to run a select * left join query
        pass

    def insert(self, table, columns, values):
        """Insert a singular row into a table"""
        # Concatenate statement
        cols, vals = get_column_value_strings(columns)
        statement = ("INSERT INTO " + str(table) + "(" + cols + ") " + "VALUES (" + vals + ")")

        # Execute statement
        self.execute(statement, values)
        self._printer('\tMySQL row successfully inserted')

    def insert_many(self, table, columns, values):
        """
        Insert multiple rows into a table.

        If only one row is found, self.insert method will be used.
        """
        # Use self.insert if only one row is being inserted
        if len(values) < 2:
            self.insert(table, columns, values[0])
        else:
            # Concatenate statement
            cols, vals = get_column_value_strings(columns)
            statement = ("INSERT INTO " + str(table) + "(" + cols + ") " + "VALUES (" + vals + ")")

            # Execute statement
            self._cursor.executemany(statement, values)
            self._printer('\tMySQL rows (' + str(len(values)) + ') successfully INSERTED')

    def insert_uniques(self, table, columns, values):
        """
        Insert multiple rows into a table that do not already exist.

        If the rows primary key already exists, the rows values will be updated.
        If the rows primary key does not exists, a new row will be inserted
        """
        # Rows that exist in the table
        existing_rows = self.select(table, columns)

        # Rows that DO NOT exist in the table
        unique = differentiate(existing_rows, values)

        # Keys that exist in the table
        keys = self.get_primary_key_values(table)

        # Primary key's column index
        pk_col = self.get_primary_key(table)
        pk_index = columns.index(pk_col)

        # Split list of unique rows into list of rows to update and rows to insert
        to_insert, to_update = [], []
        for index, row in enumerate(unique):
            # Primary key is not in list of pk values, insert new row
            if row[pk_index] not in keys:
                to_insert.append(unique[index])

            # Primary key exists, update row rather than insert
            elif row[pk_index] in keys:
                to_update.append(unique[index])

        # Insert new rows
        if len(to_insert) > 0:
            self.insert_many(table, columns, to_insert)

        # Update existing rows
        if len(to_update) > 0:
            self.update_many(table, columns, to_update, pk_col, 0)

    @staticmethod
    def _update_statement(table, columns, where):
        """Generate a SQL update statement."""
        # Unpack WHERE clause dictionary into tuple
        where_col, where_val = where

        # Create column string from list of values
        cols = get_column_value_strings(columns, query_type='update')

        # Concatenate statement
        return "UPDATE " + str(table) + " SET " + str(cols) + ' WHERE ' + str(where_col) + '=' + str(where_val)

    def update(self, table, columns, values, where):
        """
        Update the values of a particular row where a value is met.

        :param table: table name
        :param columns: column(s) to update
        :param values: updated values
        :param where: tuple, (where_column, where_value)
        """
        statement = self._update_statement(table, columns, where)

        # Execute statement
        self._cursor.execute(statement, values)
        self._printer('\tMySQL cols (' + str(len(values)) + ') successfully UPDATED')

    def update_many(self, table, columns, values, where_col, where_index):
        """Update the values of several rows."""
        for row in values:
            self.update(table, columns, row, (where_col, row[where_index]))

    def truncate(self, table):
        """Empty a table by deleting all of its rows."""
        statement = "TRUNCATE " + str(table)
        self.execute(statement)
        self._printer('\tMySQL table ' + str(table) + ' successfully truncated')

    def truncate_database(self):
        """Drop all tables in a database."""
        self.enable_printing = False
        # Loop through each table and execute a drop command
        return [self.drop_table(table) for table in
                tqdm(self.tables, total=len(self.tables), desc='Truncating database')]

    # def create_table(self, table, data, headers=None):
    #     """Generate and execute a create table query by parsing a 2D dataset"""
    #     # TODO: Fix
    #     # Set headers list
    #     if not headers:
    #         headers = data[0]
    #
    #     # Create dictionary columns and data types from headers list
    #     data_types = {header: None for header in headers}
    #
    #     # Confirm that each row of the dataset is the same length
    #     for row in data:
    #         assert len(row) == len(headers)
    #
    #     # Create list of columns
    #     columns = [header + ' ' + data_type for header, data_type in data_types]
    #     self._printer(columns)
    #     statement = "create table " + table + " ("
    #     self._printer(statement)

    def drop_table(self, table):
        """Drop a table from a database."""
        self.execute('DROP TABLE ' + table)
        return table

    def drop_empty_tables(self):
        """Drop all empty tables in a database."""
        # Count number of rows in each table
        counts = self.count_rows_all()
        drops = []

        # Loop through each table key and validate that rows count is not 0
        for table, count in counts.items():
            if count < 1:
                # Drop table if it contains no rows
                self.drop_table(table)
                self._printer('Dropped table', table)
                drops.append(table)
        return drops

    def execute_sql_script(self, sql_script):
        """Execute a sql file one command at a time."""
        # Open and read the file as a single buffer
        with open(sql_script, 'r') as fd:
            sql_file = fd.read()

        # all SQL commands (split on ';')
        # remove dbo. prefixes from table names
        sql_commands = [com.replace("dbo.", '') for com in sql_file.split(';')]
        self._printer(len(sql_commands), 'Total commands')

        # Save failed commands to list
        fails = []
        success = 0

        # Execute every command from the input file
        for command in tqdm(sql_commands, total=len(sql_commands), desc='Executing SQL Commands'):
            # This will skip and report errors
            # For example, if the tables do not yet exist, this will skip over
            # the DROP TABLE commands
            try:
                self.execute(command)
                success += 1
            except:
                fails.append(command)

        # Write fail commands to a text file
        self._printer(success, 'total successful commands')

        # Dump failed commands to text file
        if len(fails) > 1:
            # Re-add semi-colon separator
            fails = [com + ';\n' for com in fails]
            self._printer(len(fails), 'total failed commands')

            # Dump failed commands to text file in the same directory as the script
            txt_file = os.path.join(os.path.dirname(sql_script),
                                    str(os.path.basename(sql_script).strip('_fails').rsplit('.')[0]) + '_fails.sql')
            self._printer('Fail commands dumped to', txt_file)
            with open(txt_file, 'w') as txt:
                txt.writelines(fails)

    def get_schema(self, table, with_headers=False):
        """Retrieve the database schema for a particular table."""
        statement = 'desc ' + table
        f = self._fetch(statement)

        # If with_headers is True, insert headers to first row before returning
        if with_headers:
            f.insert(0, ['Column', 'Type', 'Null', 'Key', 'Default', 'Extra'])
        return f

    def get_primary_key(self, table):
        """Retrieve the column which is the primary key for a table."""
        for column in self.get_schema(table):
            if 'pri' in column[3].lower():
                return column[0]

    def get_primary_key_values(self, table):
        """Retrieve a list of primary key values in a table"""
        return self.select(table, self.get_primary_key(table), _print=False)

    def count_rows(self, table):
        """Get the number of rows in a particular table"""
        statement = 'SELECT COUNT(*) FROM ' + table
        return self._fetch(statement, _print=False)

    def count_rows_all(self):
        """Get the number of rows for every table in the database."""
        return {table: self.count_rows(table) for table in self.tables}


class MySQLTools(MySQL):
    def __init__(self, config, enable_printing=True):
        """Wrapper class for MySQL"""
        super(MySQLTools, self).__init__(config, enable_printing)
