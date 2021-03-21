"""coBib undo command."""

import argparse
import logging
import os
import subprocess
import sys

from cobib.config import config
from cobib.database import Database

from .base_command import ArgumentParser, Command

LOGGER = logging.getLogger(__name__)


class UndoCommand(Command):
    """Undo Command."""

    name = "undo"

    def execute(self, args, out=sys.stdout):
        """Undo last change.

        Undoes the last change to the database file. By default, only auto-committed changes by
        coBib will be undone. Use `--force` to undo other changes, too.

        Args: See base class.
        """
        git_tracked = config.database.git
        if not git_tracked:
            msg = (
                "You must enable coBib's git-tracking in order to use the `Undo` command."
                "\nPlease refer to the man-page for more information on how to do so."
            )
            print(msg, file=sys.stderr)
            LOGGER.error(msg)
            return

        file = os.path.realpath(os.path.expanduser(config.database.file))
        root = os.path.dirname(file)
        if not os.path.exists(os.path.join(root, ".git")):
            msg = (
                "You have configured, but not initialized coBib's git-tracking."
                "\nPlease consult `cobib init --help` for more information on how to do so."
            )
            print(msg, file=sys.stderr)
            LOGGER.error(msg)
            return

        LOGGER.debug("Starting Undo command.")
        parser = ArgumentParser(prog="undo", description="Undo subcommand parser.")
        parser.add_argument(
            "-f", "--force", action="store_true", help="allow undoing non auto-committed changes"
        )

        try:
            largs = parser.parse_args(args)
        except argparse.ArgumentError as exc:
            LOGGER.error(exc.message)
            print(exc.message, file=sys.stderr)
            return

        LOGGER.debug("Obtaining git log.")
        lines = subprocess.check_output(
            [
                "git",
                "--no-pager",
                "-C",
                f"{root}",
                "log",
                "--oneline",
                "--no-decorate",
                "--no-abbrev",
            ]
        )
        undone_shas = set()
        for commit in lines.decode().strip().split("\n"):
            LOGGER.debug("Processing commit %s", commit)
            sha, *message = commit.split()
            if message[0] == "Undo":
                # Store already undone commit sha
                LOGGER.debug("Storing undone commit sha: %s", message[-1])
                undone_shas.add(message[-1])
                continue
            if sha in undone_shas:
                LOGGER.info("Skipping %s as it was already undone", sha)
                continue
            if largs.force or (message[0] == "Auto-commit:" and message[-1] != "InitCommand"):
                # we undo a commit if and only if:
                #  - the `force` argument is specified OR
                #  - the commit is an `auto-committed` change which is NOT from `InitCommand`
                LOGGER.debug("Attempting to undo %s.", sha)
                commands = [
                    f"git -C {root} revert --no-commit {sha}",
                    f"git -C {root} commit --no-gpg-sign --quiet --message 'Undo {sha}'",
                ]
                undo = subprocess.Popen(
                    "; ".join(commands), shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                undo.communicate()
                if undo.returncode != 0:
                    LOGGER.error(
                        "Undo was unsuccessful. Please consult the logs and git history of your "
                        "database for more information."
                    )
                else:
                    # update Database
                    Database().read()
                break
        else:
            msg = "Could not find a commit to undo. Please commit something first!"
            print(msg, file=sys.stderr)
            LOGGER.warning(msg)
            sys.exit(1)

    @staticmethod
    def tui(tui):
        """See base class."""
        LOGGER.debug("Undo command triggered from TUI.")
        tui.execute_command(["undo"], skip_prompt=True)
        # update database list
        LOGGER.debug("Updating list after Undo command.")
        tui.viewport.update_list()
