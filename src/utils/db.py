import mysql.connector
from typing import Any, List, Dict

import os
from dotenv import load_dotenv

load_dotenv()


class Database:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self._connect()

    def _connect(self):
        try:
            self.conn = mysql.connector.connect(
                host=os.getenv("DB_HOST"),
                user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                database=os.getenv("DB_NAME"),
                # Fail fast if the DB is down, rather than hanging the worker
                connection_timeout=15,
            )
            self.cursor = self.conn.cursor(dictionary=True)
        except Exception as e:
            print(f"[DB_ERROR] Initialization failed: {e}")
            raise e

    def _ensure_connection(self):
        try:
            # reconnect=True will attempt to fix the link if ping fails
            # attempts=3 helps with momentary network blips
            self.conn.ping(reconnect=True, attempts=3, delay=2)
        except Exception:
            # If ping is completely broken, force a full reconnection
            print("[DB_INFO] MySQL connection lost. Reconnecting...")
            self._connect()

    def select(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        self._ensure_connection()
        # commit() before select ensures we don't get 'stale' data
        # from a previous transaction's snapshot
        self.conn.commit()
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def fetchone(self, query: str, params: tuple = ()) -> Dict[str, Any]:
        self._ensure_connection()
        self.conn.commit()
        self.cursor.execute(query, params)
        return self.cursor.fetchone()

    def execute(self, query: str, params: tuple = ()) -> int:
        self._ensure_connection()
        self.cursor.execute(query, params)
        self.conn.commit()
        return self.cursor.rowcount

    def insert(self, query: str, params: tuple) -> int:
        self._ensure_connection()
        self.cursor.execute(query, params)
        self.conn.commit()
        return self.cursor.lastrowid

    def execute_many(self, query: str, params_list: List[tuple]) -> int:
        self._ensure_connection()
        try:
            self.cursor.executemany(query, params_list)
            self.conn.commit()
            return self.cursor.rowcount
        except Exception as e:
            self.conn.rollback()
            print(f"[DB_ERROR] Bulk execute failed: {e}")
            raise e

    def update(self, query: str, params: tuple) -> int:
        return self.execute(query, params)


# Initialize
db = Database()
