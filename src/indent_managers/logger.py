import logging
import threading
from contextlib import contextmanager
from typing import Optional, Tuple, Callable, ContextManager

from src.indent_managers.base import BaseIndentManager


class LoggingIndentManager(BaseIndentManager):
    """
    Context manager for indentation-aware logging.
    """

    def __init__(self, logger: Optional[logging.Logger] = None, tab_size: int = 4, indent_char: str = ' ') -> None:
        super().__init__(tab_size, indent_char)
        self._logger = logger if logger is not None else logging.getLogger()
        self._local = threading.local()
        self._local.indent = 0

        # Create filter
        class IndentFilter(logging.Filter):
            def __init__(self, manager: 'LoggingIndentManager') -> None:
                super().__init__()
                self._manager = manager

            def filter(self, record: logging.LogRecord) -> bool:
                # Read thread-local indent if available
                indent = getattr(self._manager._local, 'indent', self._manager._indent)
                prefix = self._manager._indent_char * indent
                record.msg = prefix + str(record.getMessage())
                record.args = ()
                return True

        self._filter = IndentFilter(self)

    def __enter__(self) -> Tuple[logging.Logger, Callable[[int], ContextManager[None]]]:
        self._logger.addFilter(self._filter)

        # Override indent context to use thread-local storage
        @contextmanager
        def indent(n: int) -> ContextManager[None]:
            prev = getattr(self._local, 'indent', 0)
            self._local.indent = max(0, prev + n)
            try:
                yield
            finally:
                self._local.indent = prev

        def tab(k: int = 1) -> ContextManager[None]:
            return indent(self._tab_size * k)

        indent.tab = tab  # type: ignore[attr-defined]
        return self._logger, indent

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self._logger.removeFilter(self._filter)
        return False
