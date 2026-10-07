from __future__ import annotations

from pathlib import Path
import sqlite3
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    exact INTEGER NOT NULL DEFAULT 0,
    template_id TEXT,
    result_json TEXT,
    result_txt TEXT,
    elapsed_seconds REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id TEXT,
    event TEXT NOT NULL,
    detail TEXT,
    created_at REAL NOT NULL
);
"""


class StateDB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def completed(self, candidate_id: str, sha256: str) -> bool:
        row = self.connection.execute("SELECT status, sha256 FROM candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        return bool(row and row[1] == sha256 and row[0] not in {"running", "error", "timeout"})

    def mark_running(self, candidate_id: str, source: str, sha256: str) -> None:
        self.connection.execute(
            "INSERT INTO candidates(candidate_id,source_path,sha256,status,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(candidate_id) DO UPDATE SET source_path=excluded.source_path,sha256=excluded.sha256,status='running',updated_at=excluded.updated_at",
            (candidate_id, source, sha256, "running", time.time()),
        )
        self.connection.commit()

    def save_result(self, candidate_id: str, source: str, sha256: str, status: str, exact: bool, template_id: str | None, json_path: str, txt_path: str, elapsed: float) -> None:
        self.connection.execute(
            "INSERT INTO candidates(candidate_id,source_path,sha256,status,exact,template_id,result_json,result_txt,elapsed_seconds,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(candidate_id) DO UPDATE SET source_path=excluded.source_path,sha256=excluded.sha256,status=excluded.status,exact=excluded.exact,template_id=excluded.template_id,result_json=excluded.result_json,result_txt=excluded.result_txt,elapsed_seconds=excluded.elapsed_seconds,updated_at=excluded.updated_at",
            (candidate_id, source, sha256, status, int(exact), template_id, json_path, txt_path, elapsed, time.time()),
        )
        self.connection.commit()

    def event(self, candidate_id: str | None, event: str, detail: str = "") -> None:
        self.connection.execute("INSERT INTO events(candidate_id,event,detail,created_at) VALUES(?,?,?,?)", (candidate_id, event, detail, time.time()))
        self.connection.commit()

    def rows(self):
        return self.connection.execute("SELECT candidate_id,status,exact,template_id,elapsed_seconds,source_path FROM candidates ORDER BY candidate_id").fetchall()
