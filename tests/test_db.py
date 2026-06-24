"""Tests for db.py — uses real temporary SQLite files."""
import json
import sqlite3
from pathlib import Path

import pytest

from nctasks.db import list_groups, list_tasks


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Minimal NanoClaw data directory with one group and one session."""
    # Central DB
    central = tmp_path / "v2.db"
    conn = sqlite3.connect(central)
    conn.execute(
        "CREATE TABLE agent_groups (id TEXT PRIMARY KEY, name TEXT, folder TEXT)"
    )
    conn.execute(
        "INSERT INTO agent_groups VALUES ('ag-test-001', 'test-group', 'test-folder')"
    )
    conn.commit()
    conn.close()

    # Session inbound DB
    session_dir = tmp_path / "v2-sessions" / "ag-test-001" / "sess-test-001"
    session_dir.mkdir(parents=True)
    inbound = session_dir / "inbound.db"
    conn = sqlite3.connect(inbound)
    conn.execute(
        """CREATE TABLE messages_in (
            id TEXT, seq INTEGER, kind TEXT, timestamp TEXT, status TEXT,
            tries INTEGER DEFAULT 0, process_after TEXT, recurrence TEXT,
            platform_id TEXT, channel_type TEXT, thread_id TEXT,
            content TEXT, series_id TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO messages_in
           (id, seq, kind, timestamp, status, process_after, recurrence, content, series_id)
           VALUES (?, ?, 'task', datetime('now'), 'pending', ?, ?, ?, ?)""",
        (
            "task-001",
            2,
            "2026-06-25T06:00:00.000Z",
            "0 9 * * 1-5",
            json.dumps({"prompt": "Morning task", "script": None}),
            "task-001",
        ),
    )
    conn.execute(
        """INSERT INTO messages_in
           (id, seq, kind, timestamp, status, process_after, recurrence, content, series_id)
           VALUES (?, ?, 'task', datetime('now'), 'paused', ?, ?, ?, ?)""",
        (
            "task-002",
            4,
            "2026-06-26T14:30:00.000Z",
            None,
            json.dumps({"prompt": "One-shot task", "script": "echo '{\"wakeAgent\": false}'"}),
            "task-002",
        ),
    )
    conn.execute(
        """INSERT INTO messages_in
           (id, seq, kind, timestamp, status, process_after, recurrence, content, series_id)
           VALUES (?, ?, 'task', datetime('now'), 'pending', ?, ?, ?, ?)""",
        (
            "task-003",
            6,
            None,
            None,
            json.dumps({"prompt": "No-schedule task", "script": None}),
            "task-003",
        ),
    )
    conn.commit()
    conn.close()

    return tmp_path


def test_list_groups(data_dir: Path) -> None:
    """list_groups returns all agent groups from v2.db."""
    groups = list_groups(data_dir)
    assert len(groups) == 1
    assert groups[0].id == "ag-test-001"
    assert groups[0].name == "test-group"


def test_list_tasks_returns_both_statuses(data_dir: Path) -> None:
    """list_tasks returns pending AND paused tasks."""
    tasks = list_tasks(data_dir, "ag-test-001")
    assert len(tasks) == 3


def test_list_tasks_ordered_by_process_after(data_dir: Path) -> None:
    """Tasks are ordered process_after ASC; None sorts last."""
    tasks = list_tasks(data_dir, "ag-test-001")
    # task-001 has the earliest process_after; task-002 has a later date;
    # task-003 has process_after=None and must sort last
    assert tasks[0].series_id == "task-001"
    assert tasks[1].series_id == "task-002"
    assert tasks[2].series_id == "task-003"
    assert tasks[2].process_after is None


def test_list_tasks_type_detection(data_dir: Path) -> None:
    """Task type is 'agent' when script is None, 'scripted' when script is present."""
    tasks = list_tasks(data_dir, "ag-test-001")
    by_id = {t.series_id: t for t in tasks}
    assert by_id["task-001"].task_type == "agent"
    assert by_id["task-002"].task_type == "scripted"


def test_list_tasks_missing_sessions_dir(tmp_path: Path) -> None:
    """list_tasks returns empty list when sessions directory doesn't exist."""
    central = tmp_path / "v2.db"
    conn = sqlite3.connect(central)
    conn.execute(
        "CREATE TABLE agent_groups (id TEXT PRIMARY KEY, name TEXT, folder TEXT)"
    )
    conn.execute(
        "INSERT INTO agent_groups VALUES ('ag-empty', 'empty', 'empty-folder')"
    )
    conn.commit()
    conn.close()
    assert list_tasks(tmp_path, "ag-empty") == []
