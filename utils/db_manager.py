import sqlite3
import os

class DatabaseManager:
    def __init__(self, db_path="sakuga_bot/data/leaderboard.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS scores (
                    user_id INTEGER PRIMARY KEY,
                    points REAL DEFAULT 0
                )
            """)
            conn.commit()

    def add_point(self, user_id, amount=1):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO scores (user_id, points) 
                VALUES (?, ?) 
                ON CONFLICT(user_id) DO UPDATE SET points = points + ?
            """, (user_id, amount, amount))
            conn.commit()

    def get_top_scores(self, limit=10):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT user_id, points FROM scores ORDER BY points DESC LIMIT ?", (limit,))
            return cursor.fetchall()

    def get_user_score(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT points FROM scores WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 0
