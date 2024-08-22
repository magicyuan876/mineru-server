import sqlite3
import json
from sqlite3 import Error


class SQLiteORM:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()

    def create_table(self, create_table_sql):
        """ 创建一个表 """
        try:
            cursor = self.conn.cursor()
            cursor.execute(create_table_sql)
        except Error as e:
            print(e)
    def execute(self, sql, params=None):
        try:
            if params:
                self.cursor.execute(sql, params)
            else:
                self.cursor.execute(sql)
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error executing SQL: {e}")
            return False

    def fetchall(self, sql, params=None):
        try:
            if params:
                self.cursor.execute(sql, params)
            else:
                self.cursor.execute(sql)
            return self.cursor.fetchall()
        except Exception as e:
            print(f"Error fetching data: {e}")
            return []

    def create(self, table, data):
        columns = ', '.join(data.keys())
        placeholders = ', '.join('?' * len(data))
        sql = f'INSERT INTO {table} ({columns}) VALUES ({placeholders})'
        return self.execute(sql, tuple(data.values()))

    def read(self, table, conditions=None):
        sql = f'SELECT * FROM {table}'
        if conditions:
            where_clause = self._build_where_clause(conditions)
            sql += f' WHERE {where_clause}'
        # 注意这里的 params
        params = tuple(conditions.values()) if conditions else None
        return self.fetchall(sql, params)

    def update(self, table, data, conditions):
        set_clause = self._build_set_clause(data)
        where_clause = self._build_where_clause(conditions)
        sql = f'UPDATE {table} SET {set_clause} WHERE {where_clause}'
        # 将字典视图转换为列表或元组
        data_values = list(data.values())
        conditions_values = list(conditions.values())
        params = tuple(data_values + conditions_values)
        return self.execute(sql, params)

    def delete(self, table, conditions):
        where_clause = self._build_where_clause(conditions)
        sql = f'DELETE FROM {table} WHERE {where_clause}'
        return self.execute(sql, tuple(conditions.values()))

    def _build_set_clause(self, data):
        return ', '.join([f'{k} = ?' for k in data.keys()])

    def _build_where_clause(self, conditions):
        return ' AND '.join([f'{k} = ?' for k in conditions.keys()])

    def close(self):
        self.conn.close()

# 使用示例
if __name__ == "__main__":
    orm = SQLiteORM('example.db')

    # 创建数据
    user_data = {'id': 1, 'name': 'Alice', 'age': 25}
    orm.create('users', user_data)

    # 查询数据
    query_conditions = {'id': 1}
    users = orm.read('users', query_conditions)
    print(json.dumps(users, indent=2))

    # 更新数据
    update_data = {'name': 'Bob'}
    update_conditions = {'id': 1}
    orm.update('users', update_data, update_conditions)

    # 删除数据
    delete_conditions = {'id': 1}
    orm.delete('users', delete_conditions)

    orm.close()
