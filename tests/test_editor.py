"""Tests for editor.py — render/parse round-trips and conflict detection."""

from nctasks.db import Task
from nctasks.editor import (
    ParsedEdit,
    Snapshot,
    has_conflict,
    make_snapshot,
    parse_edit_file,
    render_edit_file,
)


def _make_task(**kwargs) -> Task:
    defaults = dict(
        series_id="task-1750000000-abc123",
        session_id="sess-1750000000-xyz",
        status="pending",
        process_after="2026-06-18T06:00:00.000Z",
        recurrence="0 9 * * 1-5",
        prompt="Do the morning checks.",
        script=None,
        task_type="agent",
        raw_content='{"prompt": "Do the morning checks.", "script": null}',
    )
    defaults.update(kwargs)
    return Task(**defaults)


# --- render ---


def test_render_contains_series_id() -> None:
    task = _make_task()
    rendered = render_edit_file(task)
    assert "task-1750000000-abc123" in rendered


def test_render_contains_prompt() -> None:
    task = _make_task()
    rendered = render_edit_file(task)
    assert "Do the morning checks." in rendered


def test_render_contains_recurrence() -> None:
    task = _make_task()
    rendered = render_edit_file(task)
    assert "0 9 * * 1-5" in rendered


def test_render_script_present() -> None:
    task = _make_task(script="echo hello", task_type="scripted")
    rendered = render_edit_file(task)
    assert "echo hello" in rendered


def test_render_empty_script_when_none() -> None:
    task = _make_task(script=None)
    rendered = render_edit_file(task)
    # Script section exists but code block is empty
    assert "## Script" in rendered


# --- parse ---


def test_parse_prompt_round_trip() -> None:
    task = _make_task()
    rendered = render_edit_file(task)
    parsed = parse_edit_file(rendered)
    assert parsed.prompt == "Do the morning checks."


def test_parse_recurrence_round_trip() -> None:
    task = _make_task()
    rendered = render_edit_file(task)
    parsed = parse_edit_file(rendered)
    assert parsed.recurrence == "0 9 * * 1-5"


def test_parse_empty_recurrence_becomes_none() -> None:
    task = _make_task(recurrence=None)
    rendered = render_edit_file(task)
    parsed = parse_edit_file(rendered)
    assert parsed.recurrence is None


def test_parse_script_round_trip() -> None:
    task = _make_task(script='echo \'{"wakeAgent": false}\'', task_type="scripted")
    rendered = render_edit_file(task)
    parsed = parse_edit_file(rendered)
    assert parsed.script is not None
    assert "wakeAgent" in parsed.script


def test_parse_empty_script_becomes_none() -> None:
    task = _make_task(script=None)
    rendered = render_edit_file(task)
    parsed = parse_edit_file(rendered)
    assert parsed.script is None


def test_parse_process_after_naive_local_to_utc() -> None:
    """Naive local timestamp in front-matter is stored back as UTC ISO 8601."""
    text = """\
<!-- nctasks edit file -->
---
id: task-abc
session_id: sess-xyz
process_after: 2026-06-18T09:00:00
recurrence:
---

## Prompt

Hello

## Script

```sh
```
"""
    parsed = parse_edit_file(text)
    # Must be a valid ISO 8601 UTC string (ends with Z)
    assert parsed.process_after.endswith("Z") or "+" in parsed.process_after


def test_parse_missing_front_matter_raises() -> None:
    import pytest
    with pytest.raises(ValueError, match="front-matter"):
        parse_edit_file("## Prompt\n\nno front matter here\n")


# --- conflict detection ---


def test_has_conflict_no_change() -> None:
    raw = '{"prompt": "hello", "script": null}'
    snap = make_snapshot(raw, "2026-06-18T06:00:00.000Z", "0 9 * * 1-5")
    current = {"content": raw, "process_after": "2026-06-18T06:00:00.000Z", "recurrence": "0 9 * * 1-5"}
    assert not has_conflict(snap, current)


def test_has_conflict_content_changed() -> None:
    snap = make_snapshot('{"prompt": "old"}', "2026-06-18T06:00:00.000Z", None)
    current = {"content": '{"prompt": "new"}', "process_after": "2026-06-18T06:00:00.000Z", "recurrence": None}
    assert has_conflict(snap, current)


def test_has_conflict_schedule_changed() -> None:
    raw = '{"prompt": "hello"}'
    snap = make_snapshot(raw, "2026-06-18T06:00:00.000Z", "0 9 * * 1-5")
    current = {"content": raw, "process_after": "2026-06-19T06:00:00.000Z", "recurrence": "0 9 * * 1-5"}
    assert has_conflict(snap, current)
