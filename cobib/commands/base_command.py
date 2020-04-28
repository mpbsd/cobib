"""CoBib Command interface"""

import argparse
import sys
from abc import ABC, abstractmethod


class Command(ABC):
    """
    The Command interface declares a method for command execution and some helper methods.
    """

    @abstractmethod
    def execute(self, args, out=sys.stdout):
        """Command execution"""

    @staticmethod
    def tui(tui):
        """TUI command interface"""


class ArgumentParser(argparse.ArgumentParser):
    """
    Overwrite ArgumentParser to allow catching any error messages thrown by parse_args.

    Source: https://stackoverflow.com/a/5943381
    """
    def _get_action_from_name(self, name):
        """Given a name, get the Action instance registered with this parser.
        If only it were made available in the ArgumentError object. It is
        passed as it's first argument...
        """
        container = self._actions
        if name is None:
            return None
        for action in container:
            if '/'.join(action.option_strings) == name:
                return action
            if action.metavar == name:
                return action
            if action.dest == name:
                return action
        return None

    def error(self, message):
        exc = sys.exc_info()[1]
        if exc:
            raise exc
        super(ArgumentParser, self).error(message)