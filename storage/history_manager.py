"""Undo / redo of project edits using JSON snapshots."""
from __future__ import annotations

from models.data_models import ProjectState


class HistoryManager:
    def __init__(self, limit: int = 50):
        self.limit = limit
        self._undo: list[tuple[str, str]] = []
        self._redo: list[tuple[str, str]] = []

    def push(self, state: ProjectState, label: str) -> None:
        """Call BEFORE modifying the state."""
        self._undo.append((label, state.to_json(indent=None)))
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self, current: ProjectState) -> tuple[ProjectState | None, str | None]:
        if not self._undo:
            return None, None
        label, js = self._undo.pop()
        self._redo.append((label, current.to_json(indent=None)))
        return ProjectState.from_json(js), label

    def redo(self, current: ProjectState) -> tuple[ProjectState | None, str | None]:
        if not self._redo:
            return None, None
        label, js = self._redo.pop()
        self._undo.append((label, current.to_json(indent=None)))
        return ProjectState.from_json(js), label

    def labels(self) -> list[str]:
        return [l for l, _ in self._undo]

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
