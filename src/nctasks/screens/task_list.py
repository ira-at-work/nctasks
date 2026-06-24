"""Task list screen — main view of nctasks."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Label

from ..db import (
    AgentGroup,
    Task,
    cancel_task,
    get_task_snapshot,
    list_tasks,
    pause_task,
    resume_task,
    update_task,
)
from ..editor import (
    has_conflict,
    make_snapshot,
    open_editor,
    parse_edit_file,
    render_edit_file,
    write_temp_file,
)


class ConfirmDeleteModal(ModalScreen[bool]):
    """Confirmation dialog for task deletion."""

    DEFAULT_CSS = """
    ConfirmDeleteModal {
        align: center middle;
    }
    ConfirmDeleteModal > Grid {
        grid-size: 2;
        grid-gutter: 1 2;
        padding: 1 2;
        width: 50;
        height: 9;
        border: thick $background 80%;
        background: $surface;
    }
    ConfirmDeleteModal Label {
        column-span: 2;
        height: 1fr;
        width: 1fr;
        content-align: center middle;
    }
    """

    BINDINGS = [
        Binding("y,enter", "confirm", "Yes — delete"),
        Binding("n,escape", "cancel", "No — keep"),
    ]

    def __init__(self, task_id_short: str) -> None:
        super().__init__()
        self.task_id_short = task_id_short

    def compose(self) -> ComposeResult:
        with Grid():
            yield Label(f"Delete task …{self.task_id_short}?")
            yield Button("Yes (y)", variant="error", id="btn-yes")
            yield Button("No (n)", variant="primary", id="btn-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


def _fmt_local(utc_str: str | None) -> str:
    if not utc_str:
        return "—"
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return utc_str


class TaskListScreen(Screen):
    """Task list for one agent group — the main working view."""

    BINDINGS = [
        Binding("e,enter", "edit", "Edit"),
        Binding("d,delete", "delete", "Delete"),
        Binding("p", "pause_resume", "Pause/Resume"),
        Binding("r", "reload", "Reload"),
        Binding("escape,q", "back", "Back"),
    ]

    def __init__(self, data_dir: Path, group: AgentGroup) -> None:
        super().__init__()
        self.data_dir = data_dir
        self.group = group
        self._tasks: list[Task] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"nctasks — {self.group.name}"
        self._load_tasks()

    def _load_tasks(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=True)
        table.add_columns("ID", "Type", "Status", "Next run", "Recurrence", "Sess", "Prompt")
        self._tasks = list_tasks(self.data_dir, self.group.id)
        for task in self._tasks:
            table.add_row(
                task.series_id[-10:],
                task.task_type,
                task.status,
                _fmt_local(task.process_after),
                task.recurrence or "—",
                task.session_id[-6:],
                task.prompt[:80].replace("\n", " "),
                key=task.series_id,
            )
        if not self._tasks:
            self.notify("No pending or paused tasks.", severity="information")
        table.focus()

    def _selected_task(self) -> Task | None:
        table = self.query_one(DataTable)
        if not self._tasks or table.cursor_row >= len(self._tasks):
            return None
        return self._tasks[table.cursor_row]

    def action_reload(self) -> None:
        self._load_tasks()
        self.notify("Reloaded.")

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_pause_resume(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        if task.status == "pending":
            pause_task(self.data_dir, self.group.id, task.session_id, task.series_id)
            self.notify(f"Paused …{task.series_id[-10:]}")
        else:
            resume_task(self.data_dir, self.group.id, task.session_id, task.series_id)
            self.notify(f"Resumed …{task.series_id[-10:]}")
        self._load_tasks()

    def action_delete(self) -> None:
        task = self._selected_task()
        if task is None:
            return
        self.app.push_screen(
            ConfirmDeleteModal(task.series_id[-10:]),
            callback=self._on_delete_result,
        )

    def _on_delete_result(self, confirmed: bool) -> None:
        if not confirmed:
            return
        task = self._selected_task()
        if task is None:
            return
        cancel_task(self.data_dir, self.group.id, task.session_id, task.series_id)
        self._load_tasks()
        self.notify(f"Deleted …{task.series_id[-10:]}")

    def action_edit(self) -> None:
        task = self._selected_task()
        if task is None:
            return

        snapshot = make_snapshot(task.raw_content, task.process_after, task.recurrence)
        tmp = write_temp_file(render_edit_file(task))

        with self.app.suspend():
            open_editor(tmp)

        try:
            edited_text = tmp.read_text()
            parsed = parse_edit_file(edited_text)
        except Exception as exc:
            self.notify(f"Parse error: {exc}", severity="error", timeout=8)
            tmp.unlink(missing_ok=True)
            return
        finally:
            tmp.unlink(missing_ok=True)

        current = get_task_snapshot(
            self.data_dir, self.group.id, task.session_id, task.series_id
        )
        if current is not None and has_conflict(snapshot, current):
            from .conflict import ConflictScreen  # noqa: PLC0415
            self.app.push_screen(
                ConflictScreen(
                    snapshot=snapshot,
                    current=current,
                    parsed=parsed,
                    data_dir=self.data_dir,
                    group_id=self.group.id,
                    session_id=task.session_id,
                    series_id=task.series_id,
                ),
                callback=self._on_conflict_resolved,
            )
        else:
            self._apply_edit(task, parsed)

    def _on_conflict_resolved(self, overwrite: bool) -> None:
        if overwrite:
            self._load_tasks()

    def _apply_edit(self, task: Task, parsed) -> None:
        update_task(
            self.data_dir,
            self.group.id,
            task.session_id,
            task.series_id,
            prompt=parsed.prompt,
            script=parsed.script,
            process_after=parsed.process_after,
            recurrence=parsed.recurrence,
        )
        self._load_tasks()
        self.notify(f"Saved …{task.series_id[-10:]}")
