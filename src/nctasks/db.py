"""NanoClaw SQLite access — read groups/tasks, write mutations."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentGroup:
    """One row from agent_groups in v2.db."""

    id: str
    name: str
    folder: str


@dataclass
class Task:
    """One pending/paused task series, merged across sessions."""

    series_id: str
    session_id: str
    status: str  # 'pending' | 'paused'
    process_after: str | None  # UTC ISO 8601 as stored in DB
    recurrence: str | None  # cron expression or None
    prompt: str  # full content.prompt
    script: str | None  # full content.script or None
    task_type: str  # 'agent' | 'scripted'
    raw_content: str  # raw JSON string for conflict detection


def list_groups(data_dir: Path) -> list[AgentGroup]:
    """Return all agent groups from v2.db, ordered by name."""
    db_path = data_dir / "v2.db"
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, name, folder FROM agent_groups ORDER BY name"
    ).fetchall()
    conn.close()
    return [AgentGroup(id=r["id"], name=r["name"], folder=r["folder"]) for r in rows]


def list_tasks(data_dir: Path, group_id: str) -> list[Task]:
    """Return all pending/paused tasks across all sessions for a group."""
    sessions_root = data_dir / "v2-sessions" / group_id
    if not sessions_root.exists():
        return []

    tasks: list[Task] = []
    seen: set[str] = set()

    for session_dir in sessions_root.iterdir():
        inbound_db = session_dir / "inbound.db"
        if not inbound_db.exists():
            continue
        session_id = session_dir.name
        try:
            conn = sqlite3.connect(f"file:{inbound_db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT series_id, status, process_after, recurrence, content,
                          MAX(seq) AS _seq
                   FROM messages_in
                   WHERE kind = 'task' AND status IN ('pending', 'paused')
                   GROUP BY series_id"""
            ).fetchall()
            conn.close()
        except sqlite3.Error:
            continue

        for row in rows:
            sid = row["series_id"]
            if sid in seen:
                continue
            seen.add(sid)
            try:
                content = json.loads(row["content"])
            except (json.JSONDecodeError, TypeError):
                content = {}
            prompt = content.get("prompt") or ""
            script = content.get("script") or None
            tasks.append(
                Task(
                    series_id=sid,
                    session_id=session_id,
                    status=row["status"],
                    process_after=row["process_after"],
                    recurrence=row["recurrence"],
                    prompt=prompt,
                    script=script,
                    task_type="scripted" if script else "agent",
                    raw_content=row["content"],
                )
            )

    tasks.sort(
        key=lambda t: (
            t.process_after is None,  # None sorts last
            t.process_after or "",
            t.series_id,
        )
    )
    return tasks
