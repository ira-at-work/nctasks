"""Group selection screen."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from ..db import AgentGroup, list_groups, list_tasks


class GroupSelectScreen(Screen):
    """List all agent groups; press Enter to open a group's task list."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, data_dir: Path) -> None:
        super().__init__()
        self.data_dir = data_dir
        self._groups: list[AgentGroup] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Name", "ID", "Pending tasks")
        self._groups = list_groups(self.data_dir)
        for group in self._groups:
            task_count = len(list_tasks(self.data_dir, group.id))
            table.add_row(group.name, group.id[-12:], str(task_count), key=group.id)
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        from .task_list import TaskListScreen

        group_id = str(event.row_key.value)
        group = next((g for g in self._groups if g.id == group_id), None)
        if group is not None:
            self.app.push_screen(TaskListScreen(self.data_dir, group))

    def action_quit(self) -> None:
        self.app.exit()
