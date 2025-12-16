from typing import Iterator, Tuple, Optional

class TexLineStream:
    def __init__(self, tex: str):
        tex = tex.replace("\r\n", "\n").replace("\r", "\n")

        if tex and not tex.endswith("\n"):
            tex += "\n"

        self._lines = tex.splitlines(keepends=True)
        self._i = 0

    def __iter__(self) -> Iterator[Tuple[int, str]]:
        while self._i < len(self._lines):
            line_num = self._i + 1
            line = self._lines[self._i]

            self._i += 1

            yield line_num, line

    def peek(self) -> Optional[Tuple[int, str]]:
        if self._i >= len(self._lines):
            return None
        
        return (self._i + 1, self._lines[self._i])

    def next(self) -> Optional[Tuple[int, str]]:
        if self._i >= len(self._lines):
            return None
        
        line_num = self._i + 1
        line = self._lines[self._i]
        
        self._i += 1

        return (line_num, line)