from __future__ import annotations

import json
import shutil
from typing import Any

import pytest
import yaml

from yougile_cli.errors import ValidationError, YouGileError
from yougile_cli.output import (
    EMPTY_NOTICE,
    ID_WIDTH,
    OutputFormat,
    OutputOptions,
    as_rows,
    available_fields,
    color_enabled,
    compact,
    fields_error,
    format_value,
    humanize_timestamp,
    notify_empty,
    print_kv,
    render,
    render_table,
    run_jq,
    sanitize_terminal_text,
    select_fields,
    set_color_override,
    shorten_id,
)

ROWS = [
    {"id": "11111111-1111-4111-8111-111111111111", "title": "Первая", "completed": False},
    {"id": "22222222-2222-4222-8222-222222222222", "title": "Вторая", "completed": True},
]


def test_output_format_values() -> None:
    assert [f.value for f in OutputFormat] == ["table", "json", "yaml", "csv", "tsv", "ids"]


def test_as_rows_unwraps_paging() -> None:
    assert as_rows({"paging": {}, "content": [{"id": "a"}]}) == [{"id": "a"}]
    assert as_rows({"id": "a"}) == [{"id": "a"}]
    assert as_rows(None) == []
    assert as_rows(["x"]) == [{"value": "x"}]


def test_shorten_id_and_booleans() -> None:
    assert shorten_id("11111111-1111-4111-8111-111111111111") == "11111111"
    assert len(shorten_id("11111111-1111-4111-8111-111111111111")) == ID_WIDTH
    assert shorten_id("abc") == "abc"
    assert compact(True) == "да"
    assert compact(False) == "нет"
    assert compact(None) == ""


def test_format_value_humanises_timestamps() -> None:
    text = format_value(1700000000000, key="timestamp")
    assert humanize_timestamp(1700000000000) == text
    assert text.startswith("2023-11")
    # Not a timestamp key: the number stays as-is.
    assert format_value(1700000000000, key="count") == "1700000000000"


def test_table_is_borderless_with_uppercase_headers(capsys: pytest.CaptureFixture[str]) -> None:
    render_table(ROWS)
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "ID        TITLE   COMPLETED"
    assert out[1] == "11111111  Первая  нет"
    assert out[2] == "22222222  Вторая  да"
    assert not any(ch in "".join(out) for ch in "│┃─═")


def test_table_full_ids(capsys: pytest.CaptureFixture[str]) -> None:
    render_table(ROWS, full_ids=True)
    assert "11111111-1111-4111-8111-111111111111" in capsys.readouterr().out


def test_table_respects_explicit_columns(capsys: pytest.CaptureFixture[str]) -> None:
    render_table(ROWS, ["title"])
    assert capsys.readouterr().out.splitlines() == ["TITLE", "Первая", "Вторая"]


def test_print_kv_aligns_keys(capsys: pytest.CaptureFixture[str]) -> None:
    print_kv({"id": "abc", "title": "Задача"})
    assert capsys.readouterr().out.splitlines() == ["id     abc", "title  Задача"]


def test_render_single_object_uses_kv(capsys: pytest.CaptureFixture[str]) -> None:
    render({"id": "abc", "title": "Задача"}, OutputOptions())
    assert "title  Задача" in capsys.readouterr().out


def test_render_json(capsys: pytest.CaptureFixture[str]) -> None:
    render({"id": "abc"}, OutputOptions(fmt=OutputFormat.JSON))
    assert json.loads(capsys.readouterr().out) == {"id": "abc"}


def test_render_yaml_csv_tsv_ids(capsys: pytest.CaptureFixture[str]) -> None:
    render(ROWS, OutputOptions(fmt=OutputFormat.YAML))
    assert "title: Первая" in capsys.readouterr().out

    render(ROWS, OutputOptions(fmt=OutputFormat.CSV), columns=["id", "title"])
    csv_out = capsys.readouterr().out.splitlines()
    assert csv_out[0] == "id,title"
    assert csv_out[1].endswith(",Первая")

    render(ROWS, OutputOptions(fmt=OutputFormat.TSV), columns=["title"])
    assert capsys.readouterr().out.splitlines() == ["title", "Первая", "Вторая"]

    render(ROWS, OutputOptions(fmt=OutputFormat.IDS))
    assert capsys.readouterr().out.splitlines() == [r["id"] for r in ROWS]


def test_render_ids_warns_when_nothing_has_an_id(capsys: pytest.CaptureFixture[str]) -> None:
    """`config list` в формате ids молча печатал ноль байт с кодом 0."""
    render([{"version": "1", "output": "ids"}], OutputOptions(fmt=OutputFormat.IDS))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ids" in captured.err
    assert "-o table" in captured.err


def test_available_fields_and_selection() -> None:
    assert available_fields(ROWS) == ["id", "title", "completed"]
    picked = select_fields(ROWS, ["title", "completed"])
    assert picked == [
        {"title": "Первая", "completed": False},
        {"title": "Вторая", "completed": True},
    ]


def test_select_fields_supports_dotted_paths() -> None:
    rows = [{"id": "a", "deadline": {"deadline": 17, "withTime": True}}]
    assert select_fields(rows, ["deadline.withTime"]) == [{"deadline.withTime": True}]


def test_select_fields_rejects_unknown_field() -> None:
    with pytest.raises(YouGileError) as excinfo:
        select_fields(ROWS, ["nope"])
    assert "nope" in str(excinfo.value)
    assert "title" in str(excinfo.value.hint)


def test_fields_error_lists_available_fields() -> None:
    error = fields_error(ROWS)
    assert error.exit_code == 1
    assert "completed" in str(error.hint)


def test_render_json_fields_forces_json(capsys: pytest.CaptureFixture[str]) -> None:
    render(ROWS, OutputOptions(fmt=OutputFormat.TABLE, json_fields=["title"]))
    assert json.loads(capsys.readouterr().out) == [{"title": "Первая"}, {"title": "Вторая"}]


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq не установлен")
def test_run_jq_filters(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_jq(ROWS, ".[].title").split() == ["Первая", "Вторая"]
    render(ROWS, OutputOptions(jq=".[0].title"))
    assert capsys.readouterr().out.strip() == "Первая"


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq не установлен")
def test_run_jq_bad_expression() -> None:
    with pytest.raises(ValidationError):
        run_jq(ROWS, "((")


def test_run_jq_without_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise FileNotFoundError("jq")

    monkeypatch.setattr("yougile_cli.output.subprocess.run", boom)
    with pytest.raises(ValidationError) as excinfo:
        run_jq(ROWS, ".")
    assert excinfo.value.exit_code == 2
    assert "jq" in str(excinfo.value.hint)


def test_color_is_off_when_not_a_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    assert color_enabled() is False
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    assert color_enabled() is True
    monkeypatch.setenv("NO_COLOR", "1")
    assert color_enabled() is True  # CLICOLOR_FORCE выигрывает
    monkeypatch.delenv("CLICOLOR_FORCE")
    assert color_enabled() is False


def test_table_has_no_ansi_when_piped(capsys: pytest.CaptureFixture[str]) -> None:
    render_table(ROWS)
    assert "\x1b[" not in capsys.readouterr().out


ESCAPE_ATTACK = "Задача\x1b]52;c;aGFjaw==\x1b\\\x1b[2J\x1b[31mFAKE"


def test_sanitize_replaces_every_control_character_with_one_placeholder() -> None:
    """Каждый вырезанный символ виден как «\ufffd», иначе название не отличить от чистого."""
    assert sanitize_terminal_text("a\x00\x01b") == "a\ufffd\ufffdb"
    assert sanitize_terminal_text("\x1b[31m") == "\ufffd[31m"
    assert sanitize_terminal_text("a\x80b\x9fc") == "a\ufffdb\ufffdc"


def test_sanitize_keeps_newline_tab_and_ordinary_text() -> None:
    assert sanitize_terminal_text("строка\nдруг\tая") == "строка\nдруг\tая"
    assert sanitize_terminal_text("Задача 🎉 «кавычки» — тире") == "Задача 🎉 «кавычки» — тире"
    assert sanitize_terminal_text("") == ""


def test_sanitize_defangs_the_osc52_clipboard_payload() -> None:
    cleaned = sanitize_terminal_text(ESCAPE_ATTACK)
    assert "\x1b" not in cleaned
    assert cleaned.startswith("Задача\ufffd")
    assert cleaned.endswith("FAKE")


def test_output_options_machine_readable() -> None:
    assert OutputOptions().machine_readable is False
    assert OutputOptions(fmt=OutputFormat.JSON).machine_readable is True
    assert OutputOptions(jq=".").machine_readable is True


def test_csv_and_tsv_defuse_spreadsheet_formulas(capsys: pytest.CaptureFixture[str]) -> None:
    """A task title is attacker-controlled; Excel evaluates a cell starting with =."""
    rows = [{"title": "=cmd|'/C calc'!A0"}, {"title": "@SUM(1)"}, {"title": "\t=1+1"}]
    render(rows, OutputOptions(fmt=OutputFormat.CSV), columns=["title"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].startswith("'=cmd")
    assert lines[2] == "'@SUM(1)"

    render(rows, OutputOptions(fmt=OutputFormat.TSV), columns=["title"])
    assert capsys.readouterr().out.splitlines()[3].startswith(("'", "\"'"))


def test_color_override_beats_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLICOLOR_FORCE", "1")
    try:
        set_color_override(False)
        assert color_enabled() is False
        set_color_override(None)
        assert color_enabled() is True
    finally:
        set_color_override(None)


# ------------------------------------------------------------------ пустой список (№2)

UUID_A = "11111111-1111-4111-8111-111111111111"
UUID_B = "22222222-2222-4222-8222-222222222222"


def test_empty_table_says_so_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """Ноль байт и код 0 неотличимы от поломки; stdout при этом обязан остаться пустым."""
    render([], OutputOptions())
    captured = capsys.readouterr()
    assert captured.out == ""
    assert EMPTY_NOTICE in captured.err


def test_empty_paging_envelope_also_notifies(capsys: pytest.CaptureFixture[str]) -> None:
    render({"paging": {"count": 0}, "content": []}, OutputOptions())
    captured = capsys.readouterr()
    assert captured.out == ""
    assert EMPTY_NOTICE in captured.err


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [(OutputFormat.JSON, "[]"), (OutputFormat.IDS, ""), (OutputFormat.CSV, "")],
)
def test_machine_formats_keep_their_empty_output(
    capsys: pytest.CaptureFixture[str], fmt: OutputFormat, expected: str
) -> None:
    render([], OutputOptions(fmt=fmt))
    captured = capsys.readouterr()
    assert captured.out.strip() == expected
    assert EMPTY_NOTICE not in captured.err


def test_notify_empty_accepts_a_message(capsys: pytest.CaptureFixture[str]) -> None:
    notify_empty(message="Вебхуков нет.")
    assert "Вебхуков нет." in capsys.readouterr().err


# --------------------------------------------------------------- сокращение id (№5)


def test_uuid_is_shortened_under_any_key() -> None:
    """createdBy печатался целиком, а id — восемью символами; правило одно на всех."""
    assert format_value(UUID_A, key="createdBy") == "11111111"
    assert format_value(UUID_A, key="title") == "11111111"
    assert format_value(UUID_A, key="createdBy", full_ids=True) == UUID_A


def test_uuid_list_is_shortened() -> None:
    assert format_value([UUID_A, UUID_B], key="assigned") == '["11111111","22222222"]'
    assert UUID_A in format_value([UUID_A], key="assigned", full_ids=True)


def test_print_kv_shortens_every_identifier(capsys: pytest.CaptureFixture[str]) -> None:
    print_kv({"id": UUID_A, "createdBy": UUID_B, "assigned": [UUID_A]})
    out = capsys.readouterr().out
    assert UUID_A not in out
    assert "createdBy  22222222" in out


def test_print_kv_full_ids(capsys: pytest.CaptureFixture[str]) -> None:
    print_kv({"createdBy": UUID_B}, full_ids=True)
    assert UUID_B in capsys.readouterr().out


def test_non_uuid_values_are_untouched() -> None:
    assert format_value("Задача про 11111111", key="title") == "Задача про 11111111"
    assert format_value("111111111111111111", key="externalId") == "11111111"


def test_csv_and_tsv_strip_escape_sequences(capsys: pytest.CaptureFixture[str]) -> None:
    """R01.2: ESC уходил в файл как есть — `cat` отчёта выполнял бы его."""
    rows = [{"title": ESCAPE_ATTACK}]
    render(rows, OutputOptions(fmt=OutputFormat.CSV), columns=["title"])
    csv_out = capsys.readouterr().out
    render(rows, OutputOptions(fmt=OutputFormat.TSV), columns=["title"])
    tsv_out = capsys.readouterr().out
    assert "\x1b" not in csv_out and "\x1b" not in tsv_out
    assert "�" in csv_out and "�" in tsv_out


def test_json_and_yaml_keep_the_original_characters_escaped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """R01.3: машинные форматы экранируют сами — очистка там потеряла бы данные."""
    rows = [{"title": ESCAPE_ATTACK}]
    render(rows, OutputOptions(fmt=OutputFormat.JSON))
    json_out = capsys.readouterr().out
    assert "\x1b" not in json_out
    assert json.loads(json_out)[0]["title"] == ESCAPE_ATTACK

    render(rows, OutputOptions(fmt=OutputFormat.YAML))
    yaml_out = capsys.readouterr().out
    assert "\x1b" not in yaml_out
    assert yaml.safe_load(yaml_out)[0]["title"] == ESCAPE_ATTACK
