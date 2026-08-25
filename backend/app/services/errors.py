from __future__ import annotations


class PanelError(Exception):

    def __init__(self, message: str, code: str = "") -> None:
        super().__init__(message)
        self.code = code
