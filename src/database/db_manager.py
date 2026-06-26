import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            # Create Series table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Create Chapters table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                series_id INTEGER NOT NULL,
                chapter_num REAL NOT NULL,
                title TEXT,
                status TEXT NOT NULL, -- 'downloaded', 'cleaned', 'ocr_completed', 'summarized'
                download_dir TEXT,
                ocr_file TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (series_id) REFERENCES series (id) ON DELETE CASCADE,
                UNIQUE (series_id, chapter_num)
            );
            """)

            # Create Summaries table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER UNIQUE NOT NULL,
                summary TEXT NOT NULL,
                characters TEXT NOT NULL, -- JSON list
                relationships TEXT NOT NULL, -- JSON list
                important_items TEXT NOT NULL, -- JSON list
                mysteries TEXT NOT NULL, -- JSON list
                key_events TEXT NOT NULL, -- JSON list
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chapter_id) REFERENCES chapters (id) ON DELETE CASCADE
            );
            """)

            # Create Arcs table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS arcs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                series_id INTEGER NOT NULL,
                start_chapter REAL NOT NULL,
                end_chapter REAL NOT NULL,
                summary TEXT NOT NULL,
                character_progression TEXT NOT NULL, -- JSON list/dict
                major_reveals TEXT NOT NULL, -- JSON list
                timeline TEXT NOT NULL, -- JSON list
                things_to_remember TEXT NOT NULL, -- JSON list
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (series_id) REFERENCES series (id) ON DELETE CASCADE,
                UNIQUE (series_id, start_chapter, end_chapter)
            );
            """)

            # Create Clean Logs table
            conn.execute("""
            CREATE TABLE IF NOT EXISTS clean_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chapter_id INTEGER NOT NULL,
                action TEXT NOT NULL, -- 'duplicate_removed', 'credit_removed'
                file_name TEXT NOT NULL,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chapter_id) REFERENCES chapters (id) ON DELETE CASCADE
            );
            """)
            conn.commit()

    # --- Series operations ---
    def get_or_create_series(self, name: str, url: Optional[str] = None) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM series WHERE name = ?;", (name,))
            row = cursor.fetchone()
            if row:
                if url:
                    cursor.execute("UPDATE series SET url = ? WHERE id = ?;", (url, row["id"]))
                return row["id"]
            
            cursor.execute("INSERT INTO series (name, url) VALUES (?, ?);", (name, url))
            conn.commit()
            return cursor.lastrowid

    def get_series(self, series_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM series WHERE id = ?;", (series_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # --- Chapter operations ---
    def get_or_create_chapter(self, series_id: int, chapter_num: float, title: Optional[str] = None, status: str = "downloaded") -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM chapters WHERE series_id = ? AND chapter_num = ?;", (series_id, chapter_num))
            row = cursor.fetchone()
            if row:
                return row["id"]
            
            cursor.execute("""
                INSERT INTO chapters (series_id, chapter_num, title, status)
                VALUES (?, ?, ?, ?);
            """, (series_id, chapter_num, title, status))
            conn.commit()
            return cursor.lastrowid

    def update_chapter(self, chapter_id: int, **kwargs) -> None:
        if not kwargs:
            return
        fields = []
        values = []
        for key, val in kwargs.items():
            fields.append(f"{key} = ?")
            values.append(val)
        values.append(chapter_id)
        
        query = f"UPDATE chapters SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?;"
        with self._get_connection() as conn:
            conn.execute(query, tuple(values))
            conn.commit()

    def get_chapter(self, series_id: int, chapter_num: float) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chapters WHERE series_id = ? AND chapter_num = ?;", (series_id, chapter_num))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_chapter_by_id(self, chapter_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chapters WHERE id = ?;", (chapter_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_chapters_by_status(self, series_id: int, status: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chapters WHERE series_id = ? AND status = ? ORDER BY chapter_num ASC;", (series_id, status))
            return [dict(row) for row in cursor.fetchall()]

    def get_all_chapters(self, series_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chapters WHERE series_id = ? ORDER BY chapter_num ASC;", (series_id,))
            return [dict(row) for row in cursor.fetchall()]

    # --- Clean log operations ---
    def add_clean_log(self, chapter_id: int, action: str, file_name: str, details: Optional[str] = None) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO clean_logs (chapter_id, action, file_name, details)
                VALUES (?, ?, ?, ?);
            """, (chapter_id, action, file_name, details))
            conn.commit()

    def get_clean_logs(self, chapter_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM clean_logs WHERE chapter_id = ? ORDER BY timestamp ASC;", (chapter_id,))
            return [dict(row) for row in cursor.fetchall()]

    # --- Summary operations ---
    def save_chapter_summary(self, chapter_id: int, summary: str, characters: List[str], relationships: List[str], 
                             important_items: List[str], mysteries: List[str], key_events: List[str]) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO summaries (chapter_id, summary, characters, relationships, important_items, mysteries, key_events)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chapter_id) DO UPDATE SET
                    summary = excluded.summary,
                    characters = excluded.characters,
                    relationships = excluded.relationships,
                    important_items = excluded.important_items,
                    mysteries = excluded.mysteries,
                    key_events = excluded.key_events;
            """, (
                chapter_id,
                summary,
                json.dumps(characters),
                json.dumps(relationships),
                json.dumps(important_items),
                json.dumps(mysteries),
                json.dumps(key_events)
            ))
            # Also update chapter status to 'summarized'
            conn.execute("UPDATE chapters SET status = 'summarized', updated_at = CURRENT_TIMESTAMP WHERE id = ?;", (chapter_id,))
            conn.commit()

    def get_chapter_summary(self, chapter_id: int) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM summaries WHERE chapter_id = ?;", (chapter_id,))
            row = cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            # Deserialize JSON fields
            data["characters"] = json.loads(data["characters"])
            data["relationships"] = json.loads(data["relationships"])
            data["important_items"] = json.loads(data["important_items"])
            data["mysteries"] = json.loads(data["mysteries"])
            data["key_events"] = json.loads(data["key_events"])
            return data

    # --- Arc operations ---
    def save_arc_summary(self, series_id: int, start_chapter: float, end_chapter: float, summary: str, 
                         character_progression: Any, major_reveals: List[str], timeline: List[str], 
                         things_to_remember: List[str]) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO arcs (series_id, start_chapter, end_chapter, summary, character_progression, major_reveals, timeline, things_to_remember)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(series_id, start_chapter, end_chapter) DO UPDATE SET
                    summary = excluded.summary,
                    character_progression = excluded.character_progression,
                    major_reveals = excluded.major_reveals,
                    timeline = excluded.timeline,
                    things_to_remember = excluded.things_to_remember;
            """, (
                series_id,
                start_chapter,
                end_chapter,
                summary,
                json.dumps(character_progression),
                json.dumps(major_reveals),
                json.dumps(timeline),
                json.dumps(things_to_remember)
            ))
            conn.commit()

    def get_arc_summary(self, series_id: int, start_chapter: float, end_chapter: float) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM arcs WHERE series_id = ? AND start_chapter = ? AND end_chapter = ?;", 
                           (series_id, start_chapter, end_chapter))
            row = cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            data["character_progression"] = json.loads(data["character_progression"])
            data["major_reveals"] = json.loads(data["major_reveals"])
            data["timeline"] = json.loads(data["timeline"])
            data["things_to_remember"] = json.loads(data["things_to_remember"])
            return data

    def get_all_arcs(self, series_id: int) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM arcs WHERE series_id = ? ORDER BY start_chapter ASC;", (series_id,))
            arcs = []
            for row in cursor.fetchall():
                data = dict(row)
                data["character_progression"] = json.loads(data["character_progression"])
                data["major_reveals"] = json.loads(data["major_reveals"])
                data["timeline"] = json.loads(data["timeline"])
                data["things_to_remember"] = json.loads(data["things_to_remember"])
                arcs.append(data)
            return arcs
