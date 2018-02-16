import psycopg2
from pygrametl.datasources import SQLSource

from common.models import DBColumn


class DatabaseConnection:
    def __init__(self, db_config):
        self.db_config = db_config

        template_db = "host='{host}' dbname='{dbname}' user='{user}' password='{password}'"

        db_string = template_db.format(
            host=self.db_config.host,
            dbname=self.db_config.name,
            user=self.db_config.user_db,
            password=self.db_config.password_db,
        )

        self.db_pgconn = psycopg2.connect(db_string)

class DatabaseExtractor(DatabaseConnection):
    def __init__(self, db_config):
        super(DatabaseExtractor, self).__init__(db_config=db_config)

    def get_tables(self, schemas, search=None):
        """
        Extracts all the tables from a database
        :param schemas: The schema to search at
        :param search: The key work to compare with the tables names
        :return: A list() of tables that match with the search
        """
        schemas_where_statement = DatabaseExtractor.prepare_schemas_where_statement(schemas)

        query = "SELECT \
                 table_name, table_schema \
                FROM information_schema.tables \
                WHERE " + schemas_where_statement + " {search} \
                ORDER BY table_name;"

        if search is not None:
            query = query.format(search=search)
        else:
            query = query.format(search="")

        return list(SQLSource(connection=self.db_pgconn, query=query))

    def get_tables_by_words(self, search_words, schemas):
        tables = self.get_tables(schemas)
        final_tables = list()

        if len(search_words) == 1:
            for table in tables:
                if table.get('table_name').find(search_words[0]) != -1:
                    final_tables.append(table)

        elif len(search_words) == 2:
            order_one = DatabaseExtractor.prepare_possibilities_order_one(search_words)
            order_two = DatabaseExtractor.prepare_possibilities_order_two(search_words)

            for table in tables:
                for word in order_one:
                    if table.get('table_name') == word:
                        final_tables.append(table)

            for table in final_tables:
                tables.remove(table)

            for table in tables:
                for word in order_two:
                    if table.get('table_name').find(word) != -1:
                        final_tables.append(table)

        return final_tables

    @staticmethod
    def prepare_possibilities_order_one(words):
        order_one_matchs = list()

        order_one_matchs.append(words[0] + words[1])
        order_one_matchs.append(words[1] + words[0])

        order_one_matchs.append(words[1] + "_" + words[0])
        order_one_matchs.append(words[0] + "_" + words[1])

        return order_one_matchs

    @staticmethod
    def prepare_possibilities_order_two(words):
        order_two_matchs = list()

        order_two_matchs.append(words[0])
        order_two_matchs.append(words[1])

        return order_two_matchs

    @staticmethod
    def prepare_schemas_where_statement(schemas):
        where_statement = "( "

        for schema in schemas:
            where_statement += "table_schema = '" + schema.name + "' OR "

        where_statement = where_statement[:-3]
        where_statement += ")"

        return where_statement


class MultiTableExtractor(DatabaseConnection):
    def __init__(self, db_config, main_table, fk_tables):
        super(MultiTableExtractor, self).__init__(db_config=db_config)

        self.main_table = main_table
        self.fk_tables = fk_tables

        self.prepare_columns_select()
        self.prepare_joins()

    def get_data(self):
        query = "SELECT " + self.columns + " FROM " + self.main_table.db_schema.name + '.' + self.main_table.name + self.joins

        data = list(SQLSource(connection=self.db_pgconn, query=query))

        sample_list = list()
        for sample_dict in data:
            sample_list.append(sample_dict)

        return sample_list

    def get_columns(self):

        columns = []
        columns.append(self.main_table.primary_key)

        # main table's columns
        for column in DBColumn.objects.filter(db_table=self.main_table):
            columns.append(column.name)

        # fk tables's columns
        for fk_table in self.fk_tables:
            for column in DBColumn.objects.filter(db_table=fk_table):
                columns.append(fk_table.name + '_' + column.name)

        return columns

    def prepare_columns_select(self):

        self.columns = self.main_table.db_schema.name + '.' + self.main_table.name + '.' + self.main_table.primary_key + ', '

        # main table's columns
        for column in DBColumn.objects.filter(db_table=self.main_table):
            self.columns += self.main_table.db_schema.name + '.' + self.main_table.name + '.' + column.name + ', '

        # fk tables's columns
        for fk_table in self.fk_tables:
            for column in DBColumn.objects.filter(db_table=fk_table):
                self.columns += fk_table.db_schema.name + '.' + fk_table.name + '.' + column.name + ' AS ' + fk_table.name + '_' + column.name + ', '

        self.columns = self.columns[:-2]

        return self.columns

    def prepare_joins(self):
        self.joins = ''

        for fk_table in self.fk_tables:
            self.joins += ' LEFT JOIN ' \
                          + fk_table.db_schema.name + '.' + fk_table.name + \
                          ' ON ' \
                          + fk_table.db_schema.name + '.' + fk_table.name + '.' + fk_table.primary_key + \
                          ' = ' \
                          + self.main_table.db_schema.name + '.' + self.main_table.name + '.' + fk_table.fk_name


class TableExtractor(DatabaseConnection):
    def __init__(self, db_config, name, schema):
        super(TableExtractor, self).__init__(db_config=db_config)

        self.table_name = name
        self.table_schema = schema

        self.special_columns = None

    def get_columns(self, special_columns=True, limit=0):
        """
        Extracts the columns of a table
        :param limit: The limits of columns to extract
        :return: A list() with the names of the columns that match with the search
        """
        query = "SELECT  column_name, data_type, character_maximum_length, numeric_precision, is_nullable \
                FROM information_schema.columns \
                WHERE table_schema = '" + self.table_schema + "' AND table_name = '" + self.table_name + "'"

        if not special_columns:
            query += " AND " + TableExtractor.not_special_columns_where_statement(self.get_special_columns())

        if limit > 0:
            query += " LIMIT " + str(limit)

        data = list(SQLSource(connection=self.db_pgconn, query=query))

        return data

    def get_special_columns(self, only_fk=False):
        """
        Extracts all primary and foreing keys columns of a table
        :return: A list() with all the primary and foreing keys columns
        """

        if self.special_columns:
            return self.special_columns

        query = "SELECT \
                    ccu.table_name, \
                    ccu.table_schema, \
                    kc.column_name, \
                    tc.constraint_type \
                FROM information_schema.table_constraints tc \
                JOIN information_schema.key_column_usage kc ON kc.table_name = tc.table_name AND kc.constraint_name = tc.constraint_name \
                JOIN information_schema.constraint_column_usage AS ccu ON ccu.constraint_name = tc.constraint_name \
                WHERE tc.table_name = '" + self.table_name + "' AND tc.table_schema = '" + self.table_schema + "'"

        if only_fk:
            query += " AND tc.constraint_type='FOREIGN KEY'"

        self.special_columns = list(SQLSource(connection=self.db_pgconn, query=query))

        return self.special_columns

    def get_data(self, columns, limit=0, offset=0):
        """
        Extract data from a table
        :param columns: The table's columns to have data extracted
        :param limit: The limit of data extracted
        :param offset: The offset to extract the data
        :return: A list() with the data extracted
        """
        if isinstance(columns, list):
            columns = TableExtractor.prepare_columns(columns)

        query = "SELECT " + columns + " FROM " + self.table_schema + "." + self.table_name

        if offset > 0:
            query += " OFFSET " + str(offset)

        if limit > 0:
            query += " LIMIT " + str(limit)

        data = list(SQLSource(connection=self.db_pgconn, query=query))

        sample_list = list()
        for sample_dict in data:
            sample_list.append(sample_dict)

        return sample_list

    def get_primary_key_name(self):
        primary_key_name = ''

        for column in self.special_columns:
            if column.get('constraint_type') == 'PRIMARY KEY':
                primary_key_name = column.get('column_name')
                break

        return primary_key_name

    @staticmethod
    def prepare_columns(columns):
        """
        Transform a list() into a string separeted with commas
        :param columns: A list() with the columns
        :return: A string with the columns
        """
        temp = ''
        for column in columns:
            if isinstance(column, list) or isinstance(column, dict):
                temp += column.get('column_name') + ', '
            else:
                temp += column + ', '

        return temp[:-2]

    @staticmethod
    def not_special_columns_where_statement(special_columns):
        where_statement = " ( "

        for column in special_columns:
            where_statement += "column_name != '" + column.get('column_name') + "' AND "

        where_statement = where_statement[:-4]
        where_statement += " ) "

        return where_statement
