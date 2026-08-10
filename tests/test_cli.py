"""Tests for the command-line entry point."""

from knowledge_assistant.cli import main


def test_cli_help(capsys: object) -> None:
    """The CLI should expose a help screen."""
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0

