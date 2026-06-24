# nctasks

Interactive TUI for viewing and editing [NanoClaw](https://github.com/nanocoai/nanoclaw) scheduled tasks.

## Installation

```sh
uv tool install nctasks
```

For local development:

```sh
git clone https://github.com/ira-at-work/nctasks
cd nctasks
uv tool install .
```

## Usage

```sh
nctasks                          # group selection screen (skipped if only one group)
nctasks --group <id-or-name>     # jump straight to task list for a specific group
nctasks --data-dir /path/to/nanoclaw/data
```

**Data directory resolution** (first match wins):

1. `--data-dir` argument
2. `NANOCLAW_DATA_DIR` environment variable
3. `./data/` — works if you run `nctasks` from inside your NanoClaw install directory

## Keybindings

### Group select screen

| Key | Action |
|-----|--------|
| `Enter` | Open task list for selected group |
| `q` | Quit |

### Task list screen

| Key | Action |
|-----|--------|
| `Enter` / `e` | Edit selected task in `$VISUAL` / `$EDITOR` |
| `d` / `Delete` | Delete task (confirmation required) |
| `p` | Pause / resume toggle |
| `r` | Reload tasks from DB |
| `Esc` / `q` | Back / quit |

## Task modes

NanoClaw supports three task modes. When you edit a task with `e`, the full task
is opened in your editor as a Markdown file. The `## Script` section controls which
mode is active.

---

### Mode 1 — Agent prompt (no script)

The agent is woken at the scheduled time and given the prompt. This is the simplest mode.

**Edit file:**

```markdown
---
id: task-1750000000-abc123
session_id: sess-1750000000-xyz
process_after: 2026-06-18T09:00:00
recurrence: 0 9 * * 1-5
---

## Prompt

Check the deploy status and post a summary to the signal group.

## Script

```
*(Leave the Script code block empty, or delete its contents entirely.)*

---

### Mode 2 — Script → agent

A script runs first and collects data (e.g. API calls, AWS queries). Its output is
injected into the agent's context alongside the prompt. The script must print a JSON
object as its **last line** with `wakeAgent: true`.

**Edit file:**

```markdown
---
id: task-1750000000-def456
session_id: sess-1750000000-xyz
process_after: 2026-06-18T06:00:00
recurrence: 0 6 * * 0-4
---

## Prompt

You are Ester. The script has fetched today's open GitHub issues.
Scan from oldest to newest. Pick the first 2 with a clear, unambiguous fix
and open PRs. Report to signal-group when done.

## Script

```sh
issues=$(gh api repos/Agrematch/agrematch/issues?state=open --jq '[.[] | {number,title}]')
echo "{\"wakeAgent\": true, \"data\": {\"issues\": $issues}}"
```
```

The `data` value is available to the agent as `scriptOutput` in the prompt context.

---

### Mode 3 — Script → send (no agent)

A script runs and posts a message directly to the session's channel. The agent is
**not** woken. If a human replies to the posted message, the agent wakes normally.

Use this for monitoring tasks that should only notify on interesting events.

**Edit file:**

```markdown
---
id: task-1750000000-ghi789
session_id: sess-1750000000-xyz
process_after: 2026-06-17T08:30:00
recurrence: */15 * * * *
---

## Prompt

Env status monitor — agent never woken; script handles everything.

## Script

```sh
#!/usr/bin/env python3
import subprocess, json

cap = json.loads(subprocess.check_output(
    ["aws", "autoscaling", "describe-auto-scaling-groups",
     "--auto-scaling-group-names", "predictor-cp-stg", "--output", "json"]
))["AutoScalingGroups"][0]["DesiredCapacity"]

status = "UP" if cap >= 6 else "DOWN"
# Only alert on DOWN; stay silent otherwise
if status == "DOWN":
    print(json.dumps({"wakeAgent": False, "send": f"⚠️ STG is DOWN (ASG desired={cap})"}))
else:
    print(json.dumps({"wakeAgent": False}))
```
```

**Script output rules:**

| Output | Effect |
|--------|--------|
| `{"wakeAgent": false, "send": "..."}` | Message posted to channel; no agent |
| `{"wakeAgent": false}` | Nothing sent; task silently completes |

---

## Edit file reference

```
<!-- nctasks edit file — keep the front-matter block intact -->
---
id: <series_id — read-only, do not change>
session_id: <session_id — read-only, do not change>
process_after: YYYY-MM-DDTHH:MM:SS      ← local time (naive) or UTC with Z suffix
recurrence: 0 9 * * 1-5                 ← cron expression; leave blank for one-shot
---

## Prompt

Full prompt text (not truncated).

## Script

```sh
# Script content. Empty block = no script (Mode 1).
```
```

`process_after` and `recurrence` are written back to the DB on save. `id` and
`session_id` are used to locate the right row — do not edit them.

On returning from the editor, nctasks checks whether the task changed in the DB
while you were editing. If it did, you are prompted to overwrite or discard.

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).
