"""Edit file render/parse and conflict detection for nctasks."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .db import Task

# Matches the front-matter block: first --- ... --- in the file.
_FM_RE = re.compile(r"---\n(.*?)\n---\n", re.DOTALL)
# Splits body into sections by ## Heading.
_SECTION_RE = re.compile(r"^## (.+)$", re.MULTILINE)
# Extracts the first fenced code block content.
_CODE_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)

_EDIT_FILE_TEMPLATE = """\
<!-- nctasks edit file — keep the front-matter block intact -->
---
id: {series_id}
session_id: {session_id}
process_after: {process_after}
recurrence: {recurrence}
---

## Prompt

{prompt}

## Script

```sh
{script}
```
"""


@dataclass
class Snapshot:
    """DB state captured before opening the editor, used for conflict detection."""

    content: str
    process_after: str | None
    recurrence: str | None


@dataclass
class ParsedEdit:
    """Validated fields extracted from the user's edited Markdown file."""

    process_after: str  # UTC ISO 8601
    recurrence: str | None
    prompt: str
    script: str | None


def render_edit_file(task: Task) -> str:
    """Render a Task to the edit file format."""
    local_dt = _utc_to_local_str(task.process_after) if task.process_after else ""
    return _EDIT_FILE_TEMPLATE.format(
        series_id=task.series_id,
        session_id=task.session_id,
        process_after=local_dt,
        recurrence=task.recurrence or "",
        prompt=task.prompt,
        script=task.script or "",
    )


def parse_edit_file(text: str) -> ParsedEdit:
    """Parse an edited Markdown file back into structured fields."""
    fm_match = _FM_RE.search(text)
    if not fm_match:
        raise ValueError("Missing front-matter block (expected --- ... ---)")

    fm = _parse_yaml(fm_match.group(1))
    process_after = _parse_process_after(fm.get("process_after", ""))
    recurrence_raw = fm.get("recurrence", "").strip()
    recurrence = recurrence_raw if recurrence_raw else None

    body = text[fm_match.end():]
    sections = _split_sections(body)

    prompt = sections.get("Prompt", "").strip()
    script_body = sections.get("Script", "")
    script = _extract_code_block(script_body)

    return ParsedEdit(
        process_after=process_after,
        recurrence=recurrence,
        prompt=prompt,
        script=script,
    )


def make_snapshot(
    raw_content: str, process_after: str | None, recurrence: str | None
) -> Snapshot:
    """Capture the DB state before opening the editor."""
    return Snapshot(
        content=raw_content, process_after=process_after, recurrence=recurrence
    )


def has_conflict(snapshot: Snapshot, current: dict) -> bool:
    """Return True if the DB row changed while the editor was open."""
    return (
        snapshot.content != current["content"]
        or snapshot.process_after != current["process_after"]
        or snapshot.recurrence != current["recurrence"]
    )


def write_temp_file(content: str) -> Path:
    """Write content to a temp .md file and return its path."""
    fd, path_str = tempfile.mkstemp(suffix=".md", prefix="nctasks-edit-")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return Path(path_str)


def open_editor(path: Path) -> None:
    """Open path in $VISUAL or $EDITOR (fallback: nano). Blocks until closed."""
    editor_cmd = os.environ.get("VISUAL") or os.environ.get("EDITOR", "nano")
    subprocess.run([*shlex.split(editor_cmd), str(path)], check=False)


# --- internal helpers ---


def _utc_to_local_str(utc_str: str) -> str:
    """Convert a UTC ISO 8601 string to a naive local datetime string."""
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return dt.astimezone().strftime("%Y-%m-%dT%H:%M:%S")


def _parse_process_after(raw: str) -> str:
    """Parse process_after from the front-matter and return UTC ISO 8601."""
    s = raw.strip()
    if not s:
        raise ValueError("process_after is required in front-matter")
    if s.endswith("Z"):
        dt = datetime.fromisoformat(s[:-1] + "+00:00")
    elif "+" in s[10:] or s.count(":") > 2:
        dt = datetime.fromisoformat(s)
    else:
        # Naive — treat as local time
        dt = datetime.fromisoformat(s).astimezone(UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_yaml(text: str) -> dict[str, str]:
    """Minimal YAML parser for the front-matter (key: value lines only)."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _split_sections(body: str) -> dict[str, str]:
    """Split a Markdown body into {section_name: content} by ## headings."""
    parts = _SECTION_RE.split(body)
    # parts: ["preamble", "Heading1", "content1", "Heading2", "content2", ...]
    sections: dict[str, str] = {}
    i = 1
    while i + 1 < len(parts):
        sections[parts[i].strip()] = parts[i + 1]
        i += 2
    return sections


def _extract_code_block(section_body: str) -> str | None:
    """Extract the first fenced code block from a section body. None if empty."""
    match = _CODE_BLOCK_RE.search(section_body)
    if not match:
        return None
    content = match.group(1).strip()
    return content if content else None
