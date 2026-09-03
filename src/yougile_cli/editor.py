"""Open $VISUAL/$EDITOR on a temporary file — typer no longer ships click.edit()."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path

from .errors import YouGileError

DEFAULT_EDITOR = "vi"


def _editor_command() -> str:
    for name in ("YOUGILE_EDITOR", "VISUAL", "EDITOR"):
        value = os.environ.get(name)
        if value:
            return value
    return DEFAULT_EDITOR


def open_editor(initial: str = "", suffix: str = ".md") -> str | None:
    """Return the edited text, or None when the user left it untouched."""
    handle, raw_path = tempfile.mkstemp(suffix=suffix, prefix="yougile-")
    path = Path(raw_path)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(initial)
        before = path.read_text(encoding="utf-8")
        setting = _editor_command()
        try:
            parts = shlex.split(setting)
        except ValueError as exc:
            raise YouGileError(
                f"Не удалось разобрать команду редактора «{setting}»: {exc}",
                hint="Проверьте переменную окружения EDITOR.",
            ) from exc
        if not parts:
            raise YouGileError(
                "Команда редактора пуста.",
                hint="Задайте переменную окружения EDITOR или используйте --body.",
            )
        command = [*parts, str(path)]
        try:
            completed = subprocess.run(command)
        except OSError as exc:
            raise YouGileError(
                f"Не удалось запустить редактор «{command[0]}»: {exc}",
                hint="Задайте переменную окружения EDITOR или используйте --body.",
            ) from exc
        if completed.returncode != 0:
            raise YouGileError(f"Редактор завершился с кодом {completed.returncode}.")
        after = path.read_text(encoding="utf-8")
    finally:
        path.unlink(missing_ok=True)
    if after == before:
        return None
    return after
