"""NcTasksApp — root Textual application."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from .db import AgentGroup


class NcTasksApp(App):
    """Root app — pushes either GroupSelectScreen or TaskListScreen on mount."""

    CSS = """
    Screen { background: $surface; }
    DataTable { height: 1fr; }
    DataTable > .datatable--header { background: $primary; color: $text; }
    """

    def __init__(self, data_dir: Path, initial_group: AgentGroup | None = None) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.initial_group = initial_group

    def on_mount(self) -> None:
        if self.initial_group is not None:
            from .screens.task_list import TaskListScreen
            self.push_screen(TaskListScreen(self.data_dir, self.initial_group))
        else:
            from .screens.group_select import GroupSelectScreen
            self.push_screen(GroupSelectScreen(self.data_dir))
