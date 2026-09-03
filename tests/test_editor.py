"""Tests for src/yougile_cli/editor.py — $EDITOR handling."""

from __future__ import annotations

import pytest

from yougile_cli.editor import open_editor
from yougile_cli.errors import YouGileError


def test_unparsable_editor_setting_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUGILE_EDITOR", 'code --wait "')
    with pytest.raises(YouGileError) as excinfo:
        open_editor("текст")
    assert "редактор" in str(excinfo.value).lower()


def test_blank_editor_setting_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUGILE_EDITOR", "   ")
    with pytest.raises(YouGileError) as excinfo:
        open_editor("текст")
    assert "редактор" in str(excinfo.value).lower()
