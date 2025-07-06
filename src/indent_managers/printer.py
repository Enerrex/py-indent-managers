import sys
from typing import Tuple, Callable, ContextManager, Optional

from src.indent_managers.base import BaseIndentManager


class PrintManager(BaseIndentManager):
    """
    Context manager for indentation-aware printing.
    """

    def __enter__(self) -> Tuple[Callable[..., None], Callable[[int], ContextManager[None]]]:
        def printer(
                *args: object,
                sep: str = ' ',
                end: str = '\n',
                file: Optional[sys.stdout.__class__] = None,
                flush: bool = False
        ) -> None:
            indent_str = self._get_indent_str()
            _file = file if file is not None else sys.stdout
            _file.write(indent_str)
            print(*args, sep=sep, end=end, file=_file, flush=flush)

        return printer, self.indent

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return False
