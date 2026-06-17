"""Entry point for the nctasks CLI."""

from __future__ import annotations

import argparse


def main() -> None:
    """Launch the nctasks TUI."""
    parser = argparse.ArgumentParser(description="Manage NanoClaw scheduled tasks")
    parser.add_argument("--group", "-g", help="Agent group ID or name (skips group selection screen)")
    _args = parser.parse_args()
    # TODO: launch Textual app
    print("nctasks — not yet implemented")


if __name__ == "__main__":
    main()
