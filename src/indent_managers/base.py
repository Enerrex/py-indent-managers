"""
indent_managers: Shared context managers for indentation-aware printing and logging.

Installation:
    pip install indent-managers

Module Version:
    __version__ = "0.1.0"

Usage Example:
    from indent_managers import PrintManager, LoggingIndentManager
    import logging

    # PrintManager
    with PrintManager(tab_size=2) as (printer, indent):
        printer("Print start")
        with indent(2):
            printer("Indented print")

    # LoggingIndentManager
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)
    with LoggingIndentManager(logger, indent_char=' ').__enter__() as (log, indent):
        log.info("Log start")
        with indent.tab(1):
            log.info("Indented log")

"""
from contextlib import contextmanager
from typing import Literal, Final, ContextManager

SPACE: Final[Literal[" "]] = " "


class BaseIndentManager:
    """
    Base class providing indentation state and context managers.
    """

    def __init__(self, tab_size: int = 4, indent_char: str = SPACE) -> None:
        self._indent: int = 0
        self._tab_size: int = tab_size
        self._indent_char: str = indent_char

        @contextmanager
        def indent(n: int) -> ContextManager[None]:
            """Temporarily adjust indentation by n characters."""
            prev = self._indent
            self._indent = max(0, prev + n)
            try:
                yield
            finally:
                self._indent = prev

        def tab(k: int = 1) -> ContextManager[None]:
            """Temporarily adjust indentation by k tabs (tab_size * k spaces)."""
            return self.indent(self._tab_size * k)

        indent.tab = tab
        self.indent = indent

    def _get_indent_str(self) -> str:
        return self._indent_char * self._indent
