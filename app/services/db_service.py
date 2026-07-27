"""Persistencia SQLite para sesiones, análisis y mensajes de chat."""
import sqlite3
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("db_service")
DB_PATH = Path("ltm_sessions.db")


class DatabaseService:
    def __init__(self):
        self._init_db()
        logger.info(f"Base de datos inicializada en {DB_PATH.resolve()}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id   TEXT PRIMARY KEY,
                    file_name    TEXT,
                    file_size    INTEGER,
                    file_path    TEXT,
                    document_text TEXT,
                    uploaded_at  TEXT,
                    analysis     TEXT,
                    risk_data    TEXT,
                    service_name TEXT,
                    analysis_error TEXT
                );
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,
                    role        TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    timestamp   TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chat_session
                    ON chat_messages(session_id);
                CREATE INDEX IF NOT EXISTS idx_session_uploaded
                    ON sessions(uploaded_at DESC);
            """)

    # ── Sessions ──────────────────────────────────────────────────────────────

    def save_session(self, session_id: str, data: Dict[str, Any]) -> None:
        rd = data.get("risk_data")
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO sessions
                (session_id, file_name, file_size, file_path, document_text,
                 uploaded_at, analysis, risk_data, service_name, analysis_error)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                session_id,
                data.get("file_name"),
                data.get("file_size"),
                data.get("file_path"),
                data.get("document_text"),
                data.get("uploaded_at"),
                data.get("analysis"),
                json.dumps(rd) if rd else None,
                data.get("service_name"),
                data.get("analysis_error"),
            ))

    def update_analysis(self, session_id: str, analysis: str,
                        risk_data: Optional[dict], service_name: Optional[str]) -> None:
        with self._conn() as conn:
            conn.execute("""
                UPDATE sessions
                SET analysis = ?, risk_data = ?, service_name = ?
                WHERE session_id = ?
            """, (
                analysis,
                json.dumps(risk_data) if risk_data else None,
                service_name,
                session_id,
            ))

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))

    def load_all_sessions(self) -> Dict[str, Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY uploaded_at DESC"
            ).fetchall()
        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            d = dict(row)
            if d.get("risk_data"):
                try:
                    d["risk_data"] = json.loads(d["risk_data"])
                except Exception:
                    d["risk_data"] = None
            result[d["session_id"]] = d
        return result

    # ── Chat messages ─────────────────────────────────────────────────────────

    def save_message(self, session_id: str, role: str,
                     content: str, timestamp: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO chat_messages (session_id, role, content, timestamp) VALUES (?,?,?,?)",
                (session_id, role, content, timestamp),
            )

    def load_messages(self, session_id: str) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content, timestamp FROM chat_messages "
                "WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]}
                for r in rows]

    # ── History ───────────────────────────────────────────────────────────────

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT session_id, file_name, uploaded_at, service_name, risk_data
                FROM sessions
                ORDER BY uploaded_at DESC
                LIMIT ?
            """, (limit,)).fetchall()
        items = []
        for row in rows:
            rd: Optional[dict] = None
            if row["risk_data"]:
                try:
                    rd = json.loads(row["risk_data"])
                except Exception:
                    pass
            items.append({
                "session_id": row["session_id"],
                "file_name": row["file_name"] or "—",
                "uploaded_at": row["uploaded_at"] or "",
                "service_name": (rd.get("service_name") if rd else None) or row["service_name"],
                "risk_level_overall": rd.get("risk_level_overall") if rd else None,
                "has_analysis": row["risk_data"] is not None,
            })
        return items


db = DatabaseService()
