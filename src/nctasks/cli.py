"""Entry point for the nctasks CLI."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .db import list_groups


def resolve_data_dir(arg: str | None) -> Path:
    """Resolve data directory: --data-dir > NANOCLAW_DATA_DIR > ./data/."""
    if arg:
        return Path(arg)
    env = os.environ.get("NANOCLAW_DATA_DIR")
    if env:
        return Path(env)
    return Path("data")


def main() -> None:
    """Launch the nctasks TUI."""
    parser = argparse.ArgumentParser(
        description="Interactive TUI for NanoClaw scheduled tasks"
    )
    parser.add_argument(
        "--group",
        "-g",
        help="Agent group ID or name — skips group selection screen",
    )
    parser.add_argument(
        "--data-dir",
        help=(
            "Path to NanoClaw data/ directory "
            "(default: NANOCLAW_DATA_DIR env var, then ./data/)"
        ),
    )
    args = parser.parse_args()

    data_dir = resolve_data_dir(args.data_dir)
    if not (data_dir / "v2.db").exists():
        print(
            f"Error: {data_dir}/v2.db not found.\n"
            "Run nctasks from inside a NanoClaw install directory, "
            "set NANOCLAW_DATA_DIR, or use --data-dir.",
            file=sys.stderr,
        )
        sys.exit(1)

    from .app import NcTasksApp  # noqa: PLC0415

    groups = list_groups(data_dir)

    initial_group = None
    if args.group:
        initial_group = next(
            (g for g in groups if args.group in (g.id, g.name)), None
        )
        if initial_group is None:
            print(
                f"Error: no group found matching '{args.group}'.\n"
                f"Available: {', '.join(g.name for g in groups)}",
                file=sys.stderr,
            )
            sys.exit(1)
    elif len(groups) == 1:
        initial_group = groups[0]

    NcTasksApp(data_dir=data_dir, initial_group=initial_group).run()


if __name__ == "__main__":
    main()
