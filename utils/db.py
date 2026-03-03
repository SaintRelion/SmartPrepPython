import mysql.connector
from typing import Any, List, Dict


class Database:
    def __init__(self, host, user, password, database):
        self.conn = mysql.connector.connect(
            host=host, user=user, password=password, database=database
        )
        self.cursor = self.conn.cursor(dictionary=True)

    def select(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def insert(self, query: str, params: tuple) -> int:
        self.cursor.execute(query, params)
        self.conn.commit()
        return self.cursor.lastrowid

    def update(self, query: str, params: tuple) -> int:
        self.cursor.execute(query, params)
        self.conn.commit()
        return self.cursor.rowcount

    def delete(self, query: str, params: tuple) -> int:
        self.cursor.execute(query, params)
        self.conn.commit()
        return self.cursor.rowcount


# Initialize
db = Database(host="localhost", user="root", password="mysql", database="smart_prep")
