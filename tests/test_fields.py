"""Tests for the static field schema behind `--json` without a value."""

from __future__ import annotations

from typing import Any

import respx

from yougile_cli.errors import EXIT_AUTH
from yougile_cli.fields import RESOURCE_FIELDS, static_fields
from yougile_cli.output import OutputOptions, apply_json_fields


def test_column_and_user_schemas_are_exactly_what_the_project_confirms() -> None:
    # Колонка: фикстура COLUMN в tests/test_columns.py плюс `column delete`,
    # который шлёт {"deleted": True}.
    assert static_fields("column") == ("boardId", "color", "deleted", "id", "title")
    # Сотрудник: фикстура IVAN в tests/test_users.py, она же LIST_COLUMNS в users.py.
    assert static_fields("user") == (
        "email",
        "id",
        "isAdmin",
        "lastActivity",
        "messengerOnly",
        "realName",
        "status",
    )


def test_task_schema_holds_the_names_the_cli_itself_sends_and_shows() -> None:
    # Каждое имя подтверждено кодом: тело `task create` в commands/tasks.py
    # и фикстура ответа task_payload() в tests/test_tasks.py.
    names = set(static_fields("task"))
    assert {
        "id",
        "title",
        "columnId",
        "description",
        "completed",
        "archived",
        "assigned",
        "deadline",
        "timeTracking",
        "stickers",
        "idTaskProject",
    } <= names


def test_unknown_resource_and_no_resource_give_an_empty_schema() -> None:
    assert static_fields("нет-такого-ресурса") == ()
    assert static_fields(None) == ()


def test_every_schema_is_a_sorted_tuple_of_unique_names() -> None:
    for resource, names in RESOURCE_FIELDS.items():
        assert isinstance(names, tuple), resource
        assert names, resource
        assert list(names) == sorted(set(names)), resource


def _listing(output: str) -> str:
    """The `доступные поля: …` line of the error, without the surrounding noise."""
    for line in output.splitlines():
        if "доступные поля:" in line:
            return line.split("доступные поля:", 1)[1].strip()
    raise AssertionError(f"перечня полей нет в выводе:\n{output}")


def test_bare_json_lists_task_fields_without_login_and_without_a_request(
    run: Any, api: respx.MockRouter
) -> None:
    result = run("task list --json", token=None)
    assert result.exit_code == 1, result.output
    assert "columnId" in _listing(result.output)
    assert "Вход" not in result.output
    assert not api.calls


def test_bare_json_lists_the_same_fields_when_the_answer_is_empty(
    run: Any, api: respx.MockRouter, paged: Any, logged_in: Any
) -> None:
    route = api.get("/api-v2/task-list").respond(json=paged([]))
    offline = run("task list --json", token=None)
    result = run("task list --json")
    assert result.exit_code == 1, result.output
    assert not route.called
    assert _listing(result.output) == _listing(offline.output)


def test_bare_json_unites_the_schema_with_what_the_command_actually_holds(run: Any) -> None:
    """`config list` знает ключи настроек из схемы, а алиасы — только из файла."""
    assert run(["alias", "set", "mine", "task list"]).exit_code == 0
    result = run("config list --json")
    assert result.exit_code == 1, result.output
    listing = _listing(result.output)
    assert "version" in listing
    assert "aliases.mine" in listing


def test_unknown_field_error_unites_the_schema_with_the_fields_that_came(
    run: Any, api: respx.MockRouter, paged: Any, logged_in: Any
) -> None:
    """Поле сверх схемы попадает в перечень, когда сервер его вернул."""
    api.get("/api-v2/task-list").respond(json=paged([{"id": "t1", "своёПоле": 1}]))
    result = run("task list --json нетТакогоПоля")
    assert result.exit_code == 1, result.output
    listing = _listing(result.output)
    assert "своёПоле" in listing
    assert "columnId" in listing


def test_without_a_schema_the_flag_travels_on_instead_of_short_circuiting() -> None:
    opts = OutputOptions()
    apply_json_fields(opts, "", "нет-такого-ресурса")
    assert opts.json_fields == []


def test_an_empty_row_list_means_the_same_as_no_rows_at_all() -> None:
    """Пустые строки — это «перечень пока неизвестен», а не «полей нет»."""
    opts = OutputOptions()
    apply_json_fields(opts, "", "нет-такого-ресурса", rows=[])
    assert opts.json_fields == []


def test_a_command_without_a_schema_keeps_its_former_path(run: Any, api: respx.MockRouter) -> None:
    """У `chat typing` схемы нет: команда идёт как прежде — до конца, через клиент."""
    result = run(["chat", "typing", "11111111-1111-4111-8111-111111111111", "--json"], token=None)
    assert result.exit_code == EXIT_AUTH, result.output
    assert not api.calls
