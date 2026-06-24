# nctasks — Design Spec

**Date:** 2026-06-17
**Status:** Approved

## Overview

`nctasks` is a standalone interactive TUI for managing NanoClaw scheduled tasks. It reads and writes NanoClaw's SQLite session databases directly, with no dependency on a running NanoClaw process or the `ncl` CLI.

Install: `uv tool install nctasks`
Launch: `nctasks [--group <id-or-name>] [--data-dir <path>]`

---

## Data Access

### Data directory resolution (in priority order)

1. `--data-dir` CLI argument
2. `NANOCLAW_DATA_DIR` environment variable
3. `./data/` (assumes the tool is run from inside a NanoClaw install)

### Databases read

- `data/v2.db` — central DB; read for agent group list (`agent_groups` table)
- `data/v2-sessions/<group_id>/<session_id>/inbound.db` — per-session task store; read and written for task operations

### Tasks

Tasks are `messages_in` rows with `kind='task'` and `status IN ('pending', 'paused')`. The stable handle is `series_id` (a recurring task's live row shares the `series_id` of its origin). The TUI matches by `series_id` for all mutations (same logic as NanoClaw's host-side `cancelTask`/`updateTask`).

### Task types (derived at read time from `content.script`)

| Type | Indicator | Behaviour |
|------|-----------|-----------|
| `agent` | `content.script` is null | Script runs optionally; agent is always woken |
| `scripted` | `content.script` is non-null | Script runs; script output's `wakeAgent` field decides whether the agent wakes |

The TUI shows a **Type** column derived from this rule. It does not attempt to parse the script to predict runtime behaviour.

---

## Screens

### GroupSelectScreen

Shown on startup unless `--group` is given or exactly one agent group exists (in which case it is skipped automatically).

- Lists all agent groups from `agent_groups` with: name, id (short), pending task count
- `Enter` — select group and push TaskListScreen
- `q` — quit

### TaskListScreen

Main view. Loads all `pending`/`paused` tasks across **all** sessions for the selected group, merged into one list ordered by `process_after ASC`.

**Table columns:**

| Column | Source |
|--------|--------|
| ID | `series_id` (last 10 chars) |
| Type | `agent` / `scripted` (from `content.script`) |
| Status | `status` |
| Next run | `process_after` (local time, human-readable) |
| Recurrence | `recurrence` cron expression, or `—` |
| Session | last 6 chars of `session_id` |
| Prompt | first 80 chars of `content.prompt` |

**Keybindings:**

| Key | Action |
|-----|--------|
| `Enter` / `e` | Edit task (external editor flow) |
| `d` / `Delete` | Delete task (confirmation modal) |
| `p` | Pause / resume toggle (no confirmation) |
| `r` | Reload all tasks from DB |
| `Esc` / `q` | Back to GroupSelectScreen (or quit if group was auto-selected) |

### ConflictScreen

Pushed after returning from the external editor when a conflict is detected (see Edit flow). Shows the conflicting fields side-by-side and offers:

- `o` — overwrite DB with the edited file content anyway
- `Esc` / `q` — discard edits, keep DB state

---

## Edit Flow

Triggered by `Enter` / `e` on a task row. This is not a Textual screen — it suspends the app and opens an external process.

1. **Snapshot** — record `(content, process_after, recurrence)` from the live DB row.
2. **Render temp file** — write a `.md` file to `$TMPDIR` (or `/tmp`) with the format below.
3. **Suspend app** — call `app.suspend()`.
4. **Open editor** — `subprocess.run([os.environ.get("VISUAL") or os.environ.get("EDITOR", "nano"), tmpfile])`.
5. **Resume app.**
6. **Conflict check** — re-read the same DB row. If `content`, `process_after`, or `recurrence` differ from the snapshot → push ConflictScreen.
7. **Parse and write** — parse the edited file (see format below), write back to the `inbound.db` that owns the task.
8. **Cleanup** — delete the temp file.

### Task modes

A task's behaviour is determined by the combination of `## Prompt` and `## Script` in the edit file:

| Mode | Script section | Script output | Result |
|------|---------------|---------------|--------|
| **Agent** | empty / absent | — | Agent is woken with the prompt |
| **Script → agent** | present | `{"wakeAgent": true, "data": {...}}` | Script runs; agent is woken with prompt + `data` injected as context |
| **Script → send** | present | `{"wakeAgent": false, "send": "..."}` | Script runs; message sent to channel; agent not woken. If a human replies, the agent wakes normally. |
| **Script silent** | present | `{"wakeAgent": false}` | Script runs; nothing sent; no agent |

### Edit file format

The edit file contains the **full, untruncated** content of the task. Every field is editable except `id` and `session_id`, which are read-only metadata used to locate the DB row.

```markdown
<!-- nctasks edit file — keep the front-matter block intact -->
---
id: task-1750000000-abc123
session_id: sess-1750000000-xyz
process_after: 2026-06-18T09:00:00
recurrence: 0 9 * * 1-5
---

## Prompt

Full task instructions for the agent. This text is always present — even for
script-only tasks it serves as human-readable documentation of what the task does.

## Script

```sh
# Mode: Agent (no script)
#   Leave this code block empty (or delete its contents).
#
# Mode: Script → agent (wakeAgent: true)
#   Script must print a JSON object as its last line: {"wakeAgent": true, "data": {...}}
#   The "data" value is injected into the agent's context alongside the prompt.
#
# Mode: Script → send (wakeAgent: false)
#   Script must print: {"wakeAgent": false, "send": "message text"}
#   The "send" text is posted to the session channel; no agent is woken.
#   If a human replies to that message, the agent wakes normally.
#
# Mode: Script silent
#   Script must print: {"wakeAgent": false}

echo '{"wakeAgent": true, "data": {}}'
```
```

**Parse rules:**

- Front-matter is YAML between the first `---` pair; `id` and `session_id` are read-only (not written back).
- `process_after` — displayed and edited in the user's system local time (naive, no offset). Written back to the DB as UTC ISO 8601. Accepts either naive local (`2026-06-18T09:00:00`) or explicit UTC (`2026-06-18T06:00:00Z`).
- `recurrence` — cron expression string; empty value clears recurrence (makes task one-shot).
- `## Prompt` section body (whitespace-stripped, full content preserved) → `content.prompt`.
- `## Script` fenced code block content (whitespace-stripped) → `content.script`; empty or absent block → `null`.

### Write-back SQL

```sql
UPDATE messages_in
SET content = ?, process_after = ?, recurrence = ?
WHERE (id = ? OR series_id = ?)
  AND kind = 'task'
  AND status IN ('pending', 'paused')
```

Parameters: `(new_content_json, new_process_after, new_recurrence, series_id, series_id)`.

---

## Delete Flow

Triggered by `d` / `Delete`. A modal overlay asks for confirmation (`y` / `Enter` to confirm, `Esc` / `n` to cancel). On confirm:

```sql
UPDATE messages_in
SET status = 'completed', recurrence = NULL
WHERE (id = ? OR series_id = ?)
  AND kind = 'task'
  AND status IN ('pending', 'paused')
```

This matches NanoClaw's `cancelTask` logic exactly.

---

## Pause / Resume

Triggered by `p`. No confirmation. Toggles `status` between `pending` and `paused`:

```sql
-- pause
UPDATE messages_in SET status = 'paused'
WHERE (id = ? OR series_id = ?) AND kind = 'task' AND status = 'pending'

-- resume
UPDATE messages_in SET status = 'pending'
WHERE (id = ? OR series_id = ?) AND kind = 'task' AND status = 'paused'
```

---

## Package structure

```
src/nctasks/
    __init__.py          version
    cli.py               argparse entry point; resolves data_dir; launches app
    db.py                sqlite3 helpers: read groups, read tasks, write mutations
    app.py               Textual App subclass; screen stack wiring
    screens/
        group_select.py  GroupSelectScreen
        task_list.py     TaskListScreen
        conflict.py      ConflictScreen
    editor.py            temp file render, suspend/resume, parse, conflict check
tests/
    test_db.py
    test_editor.py       parse round-trips; conflict detection logic
```

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `textual` | TUI framework |
| `croniter` | Human-readable next-run preview from cron expression |

`sqlite3` is stdlib. No other runtime dependencies.

---

## Out of scope (v1)

- Creating new tasks (agent-side `schedule_task` MCP tool handles this)
- Live auto-refresh (use `r` to reload)
- Viewing completed / historical task runs
- Multi-group batch operations
