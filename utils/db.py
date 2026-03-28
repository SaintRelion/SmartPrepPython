import mysql.connector
from typing import Any, List, Dict

import os
from dotenv import load_dotenv

load_dotenv()


class Database:
    def __init__(self):
        self.conn = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
        )
        self.cursor = self.conn.cursor(dictionary=True)

    def select(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        self.conn.commit()
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def fetchone(self, query: str, params: tuple = ()) -> Dict[str, Any]:
        self.conn.commit()
        self.cursor.execute(query, params)
        return self.cursor.fetchone()

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
db = Database()
