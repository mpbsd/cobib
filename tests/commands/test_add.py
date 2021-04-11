"""Tests for coBib's AddCommand."""
# pylint: disable=no-self-use,unused-argument

from itertools import zip_longest
from pathlib import Path

import pytest

from cobib.commands import AddCommand
from cobib.config import config
from cobib.database import Database

from .. import get_path_relative_to_home, get_resource
from ..tui.tui_test import TUITest
from .command_test import CommandTest

EXAMPLE_LITERATURE = get_resource("example_literature.yaml")
EXAMPLE_DUPLICATE_ENTRY_BIB = get_resource("example_duplicate_entry.bib", "commands")
EXAMPLE_DUPLICATE_ENTRY_YAML = get_resource("example_duplicate_entry.yaml", "commands")
EXAMPLE_MULTI_FILE_ENTRY_BIB = get_resource("example_multi_file_entry.bib", "commands")
EXAMPLE_MULTI_FILE_ENTRY_YAML = get_resource("example_multi_file_entry.yaml", "commands")


class TestAddCommand(CommandTest, TUITest):
    """Tests for coBib's AddCommand."""

    def get_command(self):
        """Get the command tested by this class."""
        return AddCommand

    def _assert(self, extra_filename):
        """Common assertion utility method."""
        # compare with reference file
        with open(EXAMPLE_LITERATURE, "r") as expected:
            true_lines = expected.readlines()
        with open(extra_filename, "r") as extra:
            true_lines += extra.readlines()
        with open(config.database.file, "r") as file:
            # we use zip_longest to ensure that we don't have more than we expect
            for line, truth in zip_longest(file, true_lines):
                assert line == truth

    def _assert_entry(self, label, **kwargs):
        """An additional assertion utility to check specific entry fields."""
        entry = Database()[label]
        for key, value in kwargs.items():
            assert entry.data.get(key, None) == value

    @pytest.mark.parametrize(
        ["setup"],
        [
            [{"git": False}],
            [{"git": True}],
        ],
        indirect=["setup"],
    )
    @pytest.mark.parametrize(
        ["more_args", "entry_kwargs"],
        [
            [[], {}],
            [
                ["-f", "test/debug.py"],
                {"file": get_path_relative_to_home(str(Path("test/debug.py").resolve()))},
            ],
            [["-l", "dummy_label"], {"ID": "dummy_label"}],
            [["tag"], {"tags": "tag"}],
            [["tag", "tag2"], {"tags": "tag, tag2"}],
        ],
    )
    def test_command(self, setup, more_args, entry_kwargs):
        """Test the command itself."""
        git = setup.get("git", False)

        label = entry_kwargs.get("ID", "example_multi_file_entry")
        args = ["-b", EXAMPLE_MULTI_FILE_ENTRY_BIB] + more_args

        AddCommand().execute(args)

        assert Database()[label]

        if entry_kwargs:
            self._assert_entry(label, **entry_kwargs)
        else:
            # only when we don't use extra arguments the files will match
            self._assert(EXAMPLE_MULTI_FILE_ENTRY_YAML)

        if git:
            # assert the git commit message
            # Note: we do not assert the arguments, because they depend on the available parsers
            self.assert_git_commit_message("add", None)

    def test_add_new_entry(self, setup, caplog):
        """Test adding a new plain entry."""
        AddCommand().execute(["-l", "dummy"])
        assert (
            "cobib.commands.add",
            30,
            "No input to parse. Creating new entry 'dummy' manually.",
        ) in caplog.record_tuples

        with open(config.database.file, "r") as file:
            lines = file.readlines()
            dummy_start = lines.index("dummy:\n")
            assert dummy_start > 0
            assert lines[dummy_start - 1] == "---\n"
            assert lines[dummy_start + 1] == "  ENTRYTYPE: article\n"
            assert lines[dummy_start + 2] == "  ID: dummy\n"
            assert lines[dummy_start + 3] == "...\n"

    def test_skip_manual_add_if_exists(self, setup, caplog):
        """Test manual addition is skipped if the label exists already."""
        AddCommand().execute(["-l", "einstein"])
        assert (
            "cobib.commands.add",
            30,
            "You tried to add a new entry 'einstein' which already exists!\n"
            "Please use `cobib edit einstein` instead!",
        ) in caplog.record_tuples

    def test_warning_missing_label(self, setup, caplog):
        """Test warning for missing label and any other input."""
        AddCommand().execute([""])
        assert (
            "cobib.commands.add",
            40,
            "Neither an input to parse nor a label for manual creation specified!",
        ) in caplog.record_tuples

    @pytest.mark.parametrize(
        ["setup"],
        [
            [{"git": False}],
            [{"git": True}],
        ],
        indirect=["setup"],
    )
    def test_overwrite_label(self, setup):
        """Test add command while specifying a label manually.

        Regression test against #4.
        """
        git = setup.get("git", False)
        # add potentially duplicate entry
        AddCommand().execute(["-b", EXAMPLE_DUPLICATE_ENTRY_BIB, "--label", "duplicate_resolver"])

        assert Database()["duplicate_resolver"]

        self._assert(EXAMPLE_DUPLICATE_ENTRY_YAML)

        if git:
            # assert the git commit message
            self.assert_git_commit_message("add", None)

    @pytest.mark.parametrize(
        ["setup"],
        [
            [{"git": False}],
        ],
        indirect=["setup"],
    )
    # other variants are already covered by test_command
    def test_cmdline(self, setup, monkeypatch):
        """Test the command-line access of the command."""
        self.run_module(monkeypatch, "main", ["cobib", "add", "-b", EXAMPLE_MULTI_FILE_ENTRY_BIB])
        self._assert(EXAMPLE_MULTI_FILE_ENTRY_YAML)

    def test_tui(self, setup):
        """Test the TUI access of the command."""

        def assertion(screen, logs, **kwargs):
            self._assert(EXAMPLE_MULTI_FILE_ENTRY_YAML)

            assert "example_multi_file_entry" in screen.display[1]

            expected_log = [
                ("cobib.commands.add", 10, "Add command triggered from TUI."),
                ("cobib.commands.add", 10, "Starting Add command."),
                (
                    "cobib.commands.add",
                    10,
                    "Adding entries from bibtex: '" + EXAMPLE_MULTI_FILE_ENTRY_BIB + "'.",
                ),
                ("cobib.commands.add", 20, "'example_multi_file_entry' was added to the database."),
                ("cobib.commands.add", 10, "Updating list after Add command."),
            ]
            assert [log for log in logs if log[0] == "cobib.commands.add"] == expected_log

        keys = "a-b " + EXAMPLE_MULTI_FILE_ENTRY_BIB + "\n"
        self.run_tui(keys, assertion, {})
