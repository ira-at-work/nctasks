"""ConflictScreen — shown when the DB changed while the editor was open."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, Static

from ..db import update_task
from ..editor import ParsedEdit, Snapshot


class ConflictScreen(Screen[bool]):
    """Show conflicting fields and let the user overwrite or discard."""

    BINDINGS = [
        Binding("o", "overwrite", "Overwrite DB with my edits"),
        Binding("escape,q", "discard", "Discard my edits"),
    ]

    DEFAULT_CSS = """
    ConflictScreen Static {
        padding: 0 2;
        margin-bottom: 1;
    }
    ConflictScreen .conflict-row { color: $warning; }
    ConflictScreen .header-label { color: $accent; text-style: bold; margin-top: 1; }
    """

    def __init__(
        self,
        snapshot: Snapshot,
        current: dict,
        parsed: ParsedEdit,
        data_dir: Path,
        group_id: str,
        session_id: str,
        series_id: str,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._current = current
        self._parsed = parsed
        self._data_dir = data_dir
        self._group_id = group_id
        self._session_id = session_id
        self._series_id = series_id

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label(
            "⚠  The task changed in the DB while you were editing.",
            classes="header-label",
        )
        yield Static(self._build_diff())
        yield Label(
            "Press  o  to overwrite the DB with your edits,  Esc/q  to discard.",
            classes="header-label",
        )
        yield Footer()

    def _build_diff(self) -> str:
        lines = []
        fields = [
            ("process_after", self._snapshot.process_after, self._current["process_after"]),
            ("recurrence", self._snapshot.recurrence, self._current["recurrence"]),
            ("content", self._snapshot.content, self._current["content"]),
        ]
        for name, before, after in fields:
            if before != after:
                lines.append(f"[yellow]{name}[/yellow]")
                lines.append(f"  DB now:    {str(after)[:120]}")
                lines.append(f"  Your edit: {str(before)[:120]}")
                lines.append("")
        return "\n".join(lines) if lines else "(no specific field diff available)"

    def action_overwrite(self) -> None:
        update_task(
            self._data_dir,
            self._group_id,
            self._session_id,
            self._series_id,
            prompt=self._parsed.prompt,
            script=self._parsed.script,
            process_after=self._parsed.process_after,
            recurrence=self._parsed.recurrence,
        )
        self.dismiss(True)

    def action_discard(self) -> None:
        self.dismiss(False)
