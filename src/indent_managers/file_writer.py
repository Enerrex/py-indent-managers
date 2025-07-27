from indent_managers import PrintManager


class FilePrintManager(PrintManager):
    """
    Context manager for indentation-aware printing to a file.

    Parameters:
        file_path (str): Path to the output file.
        mode (str): File open mode (e.g., 'w', 'a').
        encoding (str): File encoding (default: 'utf-8').
    """
    def __init__(
        self,
        file_path: str,
        mode: str = 'w',
        encoding: str = 'utf-8',
        tab_size: int = 4,
        indent_char: str = ' '
    ) -> None:
        super().__init__(tab_size, indent_char)
        self._file_path: str = file_path
        self._mode: str = mode
        self._encoding: str = encoding
        self._file_obj: Optional[IO[str]] = None

    def __enter__(self) -> Tuple[Callable[..., None], Callable[[int], ContextManager[None]]]:
        self._file_obj = open(self._file_path, self._mode, encoding=self._encoding)

        def printer(*args: object, sep: str = ' ', end: str = '\n', file: Optional[IO[str]] = None, flush: bool = False) -> None:
            indent_str = self._get_indent_str()
            _file = file if file is not None else self._file_obj
            if _file is None:
                raise RuntimeError("File not open for writing")
            _file.write(indent_str)
            print(*args, sep=sep, end=end, file=_file, flush=flush)

        return printer, self.indent

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if self._file_obj:
            self._file_obj.close()
        return False