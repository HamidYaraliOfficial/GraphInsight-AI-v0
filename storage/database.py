"""SQLite database (metadata + event log). All data stays on the local machine."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT, updated TEXT, image_name TEXT, chart_type TEXT,
    n_series INTEGER DEFAULT 0, n_points INTEGER DEFAULT 0, quality REAL, folder TEXT, is_sample INTEGER DEFAULT 0, notes TEXT,
    n_charts INTEGER DEFAULT 0, n_fits INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, ts TEXT, kind TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_project ON events(project_id);
"""


class Database:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or settings.DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
            cols = {r["name"] for r in c.execute("PRAGMA table_info(projects)")}
            for col in ("n_charts", "n_fits"):          # migrate databases created by older versions
                if col not in cols:
                    c.execute(f"ALTER TABLE projects ADD COLUMN {col} INTEGER DEFAULT 0")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_project(self, meta: dict) -> None:
        cols = ["id", "name", "created", "updated", "image_name", "chart_type", "n_series", "n_points", "quality", "folder", "is_sample", "notes",
                "n_charts", "n_fits"]
        vals = [meta.get(c) for c in cols]
        with self._conn() as c:
            c.execute(f"INSERT INTO projects ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
                      f"ON CONFLICT(id) DO UPDATE SET " + ",".join(f"{k}=excluded.{k}" for k in cols[1:]), vals)

    def list_projects(self, search: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM projects", []
        if search:
            q += " WHERE name LIKE ? OR image_name LIKE ? OR chart_type LIKE ?"
            args = [f"%{search}%"] * 3
        q += " ORDER BY updated DESC"
        with self._conn() as c:
            return [dict(r) for r in c.execute(q, args).fetchall()]

    def get_project(self, pid: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
            return dict(r) if r else None

    def delete_project(self, pid: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM projects WHERE id=?", (pid,))
            c.execute("DELETE FROM events WHERE project_id=?", (pid,))

    def add_event(self, pid: str, kind: str, detail: str = "") -> None:
        with self._conn() as c:
            c.execute("INSERT INTO events (project_id, ts, kind, detail) VALUES (?,?,?,?)",
                      (pid, datetime.now().isoformat(timespec="seconds"), kind, detail))

    def list_events(self, pid: str, limit: int = 200) -> list[dict]:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM events WHERE project_id=? ORDER BY id DESC LIMIT ?", (pid, limit))]

    def recent_events(self, limit: int = 12) -> list[dict]:
        with self._conn() as c:
            q = ("SELECT e.ts, e.kind, e.detail, p.name FROM events e LEFT JOIN projects p ON p.id = e.project_id "
                 "ORDER BY e.id DESC LIMIT ?")
            return [dict(r) for r in c.execute(q, (limit,))]

    def stats(self) -> dict:
        with self._conn() as c:
            r = c.execute("SELECT COUNT(*) n, COALESCE(SUM(n_series),0) s, COALESCE(SUM(n_points),0) p, COALESCE(SUM(n_charts),0) c, COALESCE(SUM(n_fits),0) f FROM projects").fetchone()
            return dict(projects=r["n"], series=r["s"], points=r["p"], charts=r["c"], fits=r["f"])
