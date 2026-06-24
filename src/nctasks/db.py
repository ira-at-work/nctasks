"""NanoClaw SQLite access — read groups and tasks (write mutations added in Task 2)."""

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
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, folder FROM agent_groups ORDER BY name"
        ).fetchall()
        return [AgentGroup(id=r["id"], name=r["name"], folder=r["folder"]) for r in rows]
    finally:
        conn.close()


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
                """SELECT m.series_id, m.status, m.process_after, m.recurrence, m.content
                   FROM messages_in m
                   INNER JOIN (
                       SELECT series_id, MAX(seq) AS max_seq
                       FROM messages_in
                       WHERE kind = 'task'
                       GROUP BY series_id
                   ) latest ON m.series_id = latest.series_id AND m.seq = latest.max_seq
                   WHERE m.kind = 'task' AND m.status IN ('pending', 'paused')"""
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


def _inbound_db(data_dir: Path, group_id: str, session_id: str) -> Path:
    return data_dir / "v2-sessions" / group_id / session_id / "inbound.db"


def cancel_task(
    data_dir: Path, group_id: str, session_id: str, series_id: str
) -> int:
    """Mark a task (and all its recurring siblings) as completed."""
    conn = sqlite3.connect(_inbound_db(data_dir, group_id, session_id))
    try:
        cur = conn.execute(
            "UPDATE messages_in SET status = 'completed', recurrence = NULL "
            "WHERE (id = ? OR series_id = ?) AND kind = 'task' "
            "AND status IN ('pending', 'paused')",
            (series_id, series_id),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def pause_task(
    data_dir: Path, group_id: str, session_id: str, series_id: str
) -> int:
    """Pause a pending task."""
    conn = sqlite3.connect(_inbound_db(data_dir, group_id, session_id))
    cur = conn.execute(
        "UPDATE messages_in SET status = 'paused' "
        "WHERE (id = ? OR series_id = ?) AND kind = 'task' AND status = 'pending'",
        (series_id, series_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount


def resume_task(
    data_dir: Path, group_id: str, session_id: str, series_id: str
) -> int:
    """Resume a paused task."""
    conn = sqlite3.connect(_inbound_db(data_dir, group_id, session_id))
    cur = conn.execute(
        "UPDATE messages_in SET status = 'pending' "
        "WHERE (id = ? OR series_id = ?) AND kind = 'task' AND status = 'paused'",
        (series_id, series_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount


def update_task(
    data_dir: Path,
    group_id: str,
    session_id: str,
    series_id: str,
    prompt: str,
    script: str | None,
    process_after: str,
    recurrence: str | None,
) -> int:
    """Update prompt, script, schedule, and recurrence for a task."""
    db_path = _inbound_db(data_dir, group_id, session_id)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, content FROM messages_in "
        "WHERE (id = ? OR series_id = ?) AND kind = 'task' "
        "AND status IN ('pending', 'paused')",
        (series_id, series_id),
    ).fetchall()

    total = 0
    for row in rows:
        try:
            content = json.loads(row["content"])
        except (json.JSONDecodeError, TypeError):
            content = {}
        content["prompt"] = prompt
        content["script"] = script
        cur = conn.execute(
            "UPDATE messages_in SET content = ?, process_after = ?, recurrence = ? "
            "WHERE id = ?",
            (json.dumps(content), process_after, recurrence, row["id"]),
        )
        total += cur.rowcount

    conn.commit()
    conn.close()
    return total


def get_task_snapshot(
    data_dir: Path, group_id: str, session_id: str, series_id: str
) -> dict | None:
    """Return current (content, process_after, recurrence) for conflict detection."""
    db_path = _inbound_db(data_dir, group_id, session_id)
    if not db_path.exists():
        return None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT content, process_after, recurrence FROM messages_in "
            "WHERE (id = ? OR series_id = ?) AND kind = 'task' "
            "AND status IN ('pending', 'paused') "
            "ORDER BY seq DESC LIMIT 1",
            (series_id, series_id),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "content": row["content"],
        "process_after": row["process_after"],
        "recurrence": row["recurrence"],
    }
