"""Tests for `yougile sticker string|sprint` commands."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
import respx
import typer
from typer.testing import CliRunner

from yougile_cli.client import YouGileClient
from yougile_cli.commands import stickers
from yougile_cli.commands.tasks import parse_datetime_to_ms
from yougile_cli.context import AppContext
from yougile_cli.errors import AmbiguousNameError, ResolveError, exit_code_for
from yougile_cli.output import OutputFormat, OutputOptions

STRING_PATH = "/api-v2/string-stickers"
SPRINT_PATH = "/api-v2/sprint-stickers"

SID = "11111111-1111-4111-8111-111111111111"
STATE_ID = "22222222-2222-4222-8222-222222222222"
BOARD_ID = "33333333-3333-4333-8333-333333333333"


@pytest.fixture
def run(api: respx.MockRouter, client: YouGileClient, runner: CliRunner) -> Callable[..., Any]:
    """Invoke the sticker sub-app with an AppContext holding the mocked client."""

    def _run(
        args: list[str] | str,
        *,
        input: str | None = None,
        fmt: OutputFormat = OutputFormat.JSON,
    ) -> Any:
        root = typer.Typer()
        root.add_typer(stickers.app, name="sticker")

        @root.callback()
        def _root(ctx: typer.Context) -> None:
            app_ctx = AppContext(out=OutputOptions(fmt=fmt))
            app_ctx.set_client(client)
            ctx.obj = app_ctx

        argv = args.split() if isinstance(args, str) else list(args)
        return runner.invoke(root, argv, input=input)

    return _run


def payload(route: Any) -> Any:
    return json.loads(route.calls.last.request.content)


def query(route: Any) -> dict[str, str]:
    return dict(route.calls.last.request.url.params)


def data(result: Any) -> Any:
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


# --------------------------------------------------------------------------- string


def test_string_list(run: Any, api: respx.MockRouter, paged: Any) -> None:
    route = api.get(STRING_PATH).respond(
        json=paged([{"id": SID, "name": "Приоритет", "icon": "prio"}])
    )
    result = run("sticker string list")
    assert [item["name"] for item in data(result)] == ["Приоритет"]
    assert query(route)["limit"] == "30"


def test_string_list_filters(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get("/api-v2/boards").respond(json=paged([{"id": BOARD_ID, "title": "Разработка"}]))
    route = api.get(STRING_PATH).respond(json=paged([]))
    result = run(
        ["sticker", "string", "list", "-S", "Приоритет", "-b", "Разработка", "--include-deleted"]
    )
    assert result.exit_code == 0, result.output
    params = query(route)
    assert params["name"] == "Приоритет"
    assert params["boardId"] == BOARD_ID
    assert params["includeDeleted"] == "true"


def test_string_list_limit_zero_fetches_everything(
    run: Any, api: respx.MockRouter, paged: Any
) -> None:
    route = api.get(STRING_PATH).respond(json=paged([{"id": SID, "name": "A"}]))
    assert run("sticker string list -L 0").exit_code == 0
    assert query(route)["limit"] == "1000"


def test_string_view_resolves_name(run: Any, api: respx.MockRouter, paged: Any) -> None:
    lookup = api.get(STRING_PATH).respond(json=paged([{"id": SID, "name": "Приоритет"}]))
    api.get(f"{STRING_PATH}/{SID}").respond(
        json={"id": SID, "name": "Приоритет", "icon": "prio", "states": []}
    )
    result = run(["sticker", "string", "view", "Приоритет"])
    assert data(result)["id"] == SID
    assert query(lookup)["name"] == "Приоритет"


def test_string_icons(run: Any) -> None:
    icons = [row["icon"] for row in data(run("sticker string icons"))]
    assert "prio" in icons
    assert "" not in icons


def test_string_create(run: Any, api: respx.MockRouter) -> None:
    route = api.post(STRING_PATH).respond(201, json={"id": SID})
    result = run(
        ["sticker", "string", "create", "Приоритет", "--icon", "prio", "-s", "Высокий:red"]
    )
    assert data(result)["id"] == SID
    assert payload(route) == {
        "name": "Приоритет",
        "icon": "prio",
        "states": [{"name": "Высокий", "color": "red"}],
    }


def test_string_create_rejects_unknown_icon(run: Any) -> None:
    result = run(["sticker", "string", "create", "Тест", "--icon", "banana"])
    assert exit_code_for(result.exception) == 2
    assert "banana" in str(result.exception)


def test_string_edit(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"{STRING_PATH}/{SID}").respond(json={"id": SID})
    result = run(["sticker", "string", "edit", SID, "--name", "Важность", "-i", "flag"])
    assert data(result)["id"] == SID
    assert payload(route) == {"name": "Важность", "icon": "flag"}


def test_string_edit_without_changes(run: Any) -> None:
    assert exit_code_for(run(["sticker", "string", "edit", SID]).exception) == 2


def test_string_delete_is_a_put(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"{STRING_PATH}/{SID}").respond(json={"id": SID})
    assert run(["sticker", "string", "delete", SID, "--yes"]).exit_code == 0
    assert payload(route) == {"deleted": True}
    assert route.calls.last.request.method == "PUT"


def test_string_delete_without_yes_outside_tty(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"{STRING_PATH}/{SID}").respond(json={"id": SID})
    result = run(["sticker", "string", "delete", SID])
    assert exit_code_for(result.exception) == 2
    assert not route.called


def test_string_delete_respects_prompt_disabled(
    api: respx.MockRouter,
    client: YouGileClient,
    runner: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`prompt: disabled` в config.yml отключает вопрос и здесь, как и в остальных командах."""
    monkeypatch.setattr(stickers, "is_tty", lambda *_a: True)
    route = api.put(f"{STRING_PATH}/{SID}").respond(json={"id": SID})

    root = typer.Typer()
    root.add_typer(stickers.app, name="sticker")

    @root.callback()
    def _root(ctx: typer.Context) -> None:
        app_ctx = AppContext(out=OutputOptions(fmt=OutputFormat.TABLE), prompt_enabled=False)
        app_ctx.set_client(client)
        ctx.obj = app_ctx

    result = runner.invoke(root, ["sticker", "string", "delete", SID], input="д\n")
    assert exit_code_for(result.exception) == 2
    assert not route.called


def test_string_state_list_hides_deleted(run: Any, api: respx.MockRouter) -> None:
    api.get(f"{STRING_PATH}/{SID}").respond(
        json={
            "id": SID,
            "name": "Приоритет",
            "states": [
                {"id": STATE_ID, "name": "Высокий", "color": "red"},
                {"id": "gone", "name": "Старый", "deleted": True},
            ],
        }
    )
    rows = data(run(["sticker", "string", "state", "list", SID]))
    assert [row["name"] for row in rows] == ["Высокий"]


def test_string_state_add(run: Any, api: respx.MockRouter) -> None:
    route = api.post(f"{STRING_PATH}/{SID}/states").respond(201, json={"id": STATE_ID})
    result = run(["sticker", "string", "state", "add", SID, "Высокий", "--color", "red"])
    assert data(result)["id"] == STATE_ID
    assert payload(route) == {"name": "Высокий", "color": "red"}


def test_string_state_edit_resolves_state_name(run: Any, api: respx.MockRouter) -> None:
    api.get(f"{STRING_PATH}/{SID}").respond(
        json={"id": SID, "name": "Приоритет", "states": [{"id": STATE_ID, "name": "Высокий"}]}
    )
    route = api.put(f"{STRING_PATH}/{SID}/states/{STATE_ID}").respond(json={"id": STATE_ID})
    result = run(["sticker", "string", "state", "edit", SID, "Высокий", "-c", "green"])
    assert data(result)["id"] == STATE_ID
    assert payload(route) == {"color": "green"}


def test_string_state_delete_is_a_put(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"{STRING_PATH}/{SID}/states/{STATE_ID}").respond(json={"id": STATE_ID})
    result = run(["sticker", "string", "state", "delete", SID, STATE_ID, "-y"])
    assert result.exit_code == 0, result.output
    assert payload(route) == {"deleted": True}


def test_unknown_state_name_raises_resolve_error(run: Any, api: respx.MockRouter) -> None:
    api.get(f"{STRING_PATH}/{SID}").respond(json={"id": SID, "name": "Приоритет", "states": []})
    result = run(["sticker", "string", "state", "delete", SID, "Нет такого", "-y"])
    assert isinstance(result.exception, ResolveError)
    assert exit_code_for(result.exception) == 1


def test_ambiguous_state_name(run: Any, api: respx.MockRouter) -> None:
    api.get(f"{STRING_PATH}/{SID}").respond(
        json={
            "id": SID,
            "name": "Приоритет",
            "states": [{"id": "a", "name": "Дубль"}, {"id": "b", "name": "Дубль"}],
        }
    )
    result = run(["sticker", "string", "state", "delete", SID, "Дубль", "-y"])
    assert isinstance(result.exception, AmbiguousNameError)
    assert exit_code_for(result.exception) == 1


# --------------------------------------------------------------------------- sprint


def test_sprint_list(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get(SPRINT_PATH).respond(json=paged([{"id": SID, "name": "Спринты"}]))
    assert [row["name"] for row in data(run("sticker sprint list"))] == ["Спринты"]


def test_sprint_view(run: Any, api: respx.MockRouter) -> None:
    api.get(f"{SPRINT_PATH}/{SID}").respond(json={"id": SID, "name": "Спринты", "states": []})
    assert data(run(["sticker", "sprint", "view", SID]))["name"] == "Спринты"


def test_sprint_create_converts_dates(run: Any, api: respx.MockRouter) -> None:
    route = api.post(SPRINT_PATH).respond(201, json={"id": SID})
    result = run(["sticker", "sprint", "create", "Спринты", "-s", "Спринт 1;2024-03-01;2024-03-14"])
    assert data(result)["id"] == SID
    assert payload(route) == {
        "name": "Спринты",
        "states": [
            {
                "name": "Спринт 1",
                "begin": parse_datetime_to_ms("2024-03-01"),
                "end": parse_datetime_to_ms("2024-03-14"),
            }
        ],
    }


def test_sprint_edit(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"{SPRINT_PATH}/{SID}").respond(json={"id": SID})
    assert run(["sticker", "sprint", "edit", SID, "-n", "Спринты Q1"]).exit_code == 0
    assert payload(route) == {"name": "Спринты Q1"}


def test_sprint_delete_is_a_put(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"{SPRINT_PATH}/{SID}").respond(json={"id": SID})
    assert run(["sticker", "sprint", "delete", SID, "-y"]).exit_code == 0
    assert payload(route) == {"deleted": True}


def test_sprint_state_list_humanizes_dates_in_table(run: Any, api: respx.MockRouter) -> None:
    begin = parse_datetime_to_ms("2024-03-01")
    api.get(f"{SPRINT_PATH}/{SID}").respond(
        json={
            "id": SID,
            "name": "Спринты",
            "states": [{"id": STATE_ID, "name": "Спринт 1", "begin": begin, "end": begin}],
        }
    )
    result = run(["sticker", "sprint", "state", "list", SID], fmt=OutputFormat.TABLE)
    assert result.exit_code == 0, result.output
    assert "2024-03-01" in result.stdout


def test_sprint_state_add(run: Any, api: respx.MockRouter) -> None:
    route = api.post(f"{SPRINT_PATH}/{SID}/states").respond(201, json={"id": STATE_ID})
    result = run(["sticker", "sprint", "state", "add", SID, "Спринт 1", "--begin", "2024-03-01"])
    assert data(result)["id"] == STATE_ID
    # Literal epoch, computed without the SUT: the date is a local wall clock.
    assert payload(route) == {
        "name": "Спринт 1",
        "begin": int(datetime(2024, 3, 1).timestamp() * 1000),
    }


def test_sprint_state_edit(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"{SPRINT_PATH}/{SID}/states/{STATE_ID}").respond(json={"id": STATE_ID})
    result = run(["sticker", "sprint", "state", "edit", SID, STATE_ID, "--end", "2024-03-20 18:00"])
    assert result.exit_code == 0, result.output
    assert payload(route) == {"end": int(datetime(2024, 3, 20, 18, 0).timestamp() * 1000)}


def test_sprint_state_delete_is_a_put(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"{SPRINT_PATH}/{SID}/states/{STATE_ID}").respond(json={"id": STATE_ID})
    assert run(["sticker", "sprint", "state", "delete", SID, STATE_ID, "-y"]).exit_code == 0
    assert payload(route) == {"deleted": True}


# --------------------------------------------------------------------------- output flags


def test_json_field_selection(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get(STRING_PATH).respond(
        json=paged([{"id": SID, "name": "Приоритет", "icon": "prio", "states": []}])
    )
    rows = data(run(["sticker", "string", "list", "--json", "id,name"], fmt=OutputFormat.TABLE))
    assert rows == [{"id": SID, "name": "Приоритет"}]


def test_empty_json_lists_available_fields(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get(STRING_PATH).respond(json=paged([{"id": SID, "name": "Приоритет"}]))
    result = run(["sticker", "string", "list", "--json", ""])
    assert exit_code_for(result.exception) == 1
    assert "name" in str(result.exception.hint or "")


def test_api_error_propagates(run: Any, api: respx.MockRouter) -> None:
    api.get(f"{STRING_PATH}/{SID}").respond(404, json={"message": "not found"})
    result = run(["sticker", "string", "view", SID])
    assert exit_code_for(result.exception) == 1


# ------------------------------------------------------- defect 1: name argument


def test_string_create_accepts_name_flag(run: Any, api: respx.MockRouter) -> None:
    """`--name` is the scripting synonym of the positional НАЗВАНИЕ."""
    route = api.post(STRING_PATH).respond(201, json={"id": SID})
    result = run(["sticker", "string", "create", "--name", "Приоритет"])
    assert data(result)["id"] == SID
    assert payload(route) == {"name": "Приоритет"}


def test_string_create_conflicting_names_is_usage_error(run: Any, api: respx.MockRouter) -> None:
    route = api.post(STRING_PATH).respond(201, json={"id": SID})
    result = run(["sticker", "string", "create", "Приоритет", "--name", "Другое"])
    assert exit_code_for(result.exception) == 2
    assert not route.called


def test_string_create_without_name_is_usage_error(run: Any, api: respx.MockRouter) -> None:
    route = api.post(STRING_PATH).respond(201, json={"id": SID})
    result = run(["sticker", "string", "create"])
    assert exit_code_for(result.exception) == 2
    assert not route.called


def test_sprint_create_accepts_name_flag(run: Any, api: respx.MockRouter) -> None:
    route = api.post(SPRINT_PATH).respond(201, json={"id": SID})
    result = run(["sticker", "sprint", "create", "--name", "Спринт 1"])
    assert data(result)["id"] == SID
    assert payload(route) == {"name": "Спринт 1"}


def test_sprint_create_conflicting_names_is_usage_error(run: Any, api: respx.MockRouter) -> None:
    route = api.post(SPRINT_PATH).respond(201, json={"id": SID})
    result = run(["sticker", "sprint", "create", "Спринт 1", "--name", "Спринт 2"])
    assert exit_code_for(result.exception) == 2
    assert not route.called


def test_sticker_metavars_are_russian(run: Any) -> None:
    for args, expected in (
        (["sticker", "string", "create", "--help"], "НАЗВАНИЕ"),
        (["sticker", "string", "view", "--help"], "СТИКЕР"),
        (["sticker", "string", "list", "--help"], "ЧИСЛО"),
        (["sticker", "sprint", "state", "edit", "--help"], "СОСТОЯНИЕ"),
    ):
        output = run(args).output
        assert expected in output
        assert "TEXT" not in output
        assert "INTEGER" not in output


# ------------------------------------------------------- defect 3: gendered wording


def test_missing_string_sticker_says_ne_najden(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get(STRING_PATH).respond(json=paged([]))
    result = run(["sticker", "string", "view", "нет-такого"])
    assert exit_code_for(result.exception) == 1
    assert str(result.exception) == "Строковый стикер «нет-такого» не найден."


# ------------------------------------------------------- defect 4: server 400 is exit 1


def test_server_400_is_runtime_error_not_usage(run: Any, api: respx.MockRouter) -> None:
    api.put(f"{STRING_PATH}/{SID}").respond(400, json={"message": "Стикер используется"})
    result = run(["sticker", "string", "delete", SID, "--yes"])
    assert exit_code_for(result.exception) == 1
    assert "Стикер используется" in str(result.exception)
