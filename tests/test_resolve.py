from __future__ import annotations

import json
import stat
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from yougile_cli.client import YouGileClient
from yougile_cli.errors import AmbiguousNameError, ResolveError, ValidationError
from yougile_cli.resolve import (
    TASK_CACHE_TTL,
    TaskRef,
    account_tag,
    extract_id_from_url,
    is_uuid,
    parse_field_pairs,
    parse_kv_options,
    parse_task_url,
    resolve_board_id,
    resolve_column_id,
    resolve_project_id,
    resolve_task_code,
    resolve_task_id,
    resolve_user_id,
    task_cache_path,
)

BOARD = "aaaaaaaa-1111-4111-8111-111111111111"
TASK = "bbbbbbbb-2222-4222-8222-222222222222"
STICKER = "cccccccc-3333-4333-8333-333333333333"


def test_is_uuid() -> None:
    assert is_uuid(BOARD) is True
    assert is_uuid("  " + BOARD.upper() + "  ") is True
    assert is_uuid("not-a-uuid") is False
    assert is_uuid("") is False


def test_extract_id_from_url() -> None:
    assert extract_id_from_url(f"https://ru.yougile.com/board/{BOARD}") == BOARD
    assert extract_id_from_url(f"https://ru.yougile.com/board/{BOARD}#sticker-{STICKER}") == STICKER
    assert extract_id_from_url(f"https://ru.yougile.com/team/x#chat-{TASK}") == TASK
    assert extract_id_from_url(f"https://ru.yougile.com/board/{BOARD}#{TASK}") == TASK
    assert extract_id_from_url("Обычное название") is None
    assert extract_id_from_url("") is None


def test_extract_id_from_url_reports_ids_and_codes_apart() -> None:
    """Ссылка из интерфейса не содержит идентификатора — только код задачи."""
    team = extract_id_from_url("https://ru.yougile.com/team/a1b2c3d4e5f6/#ILS-343")
    assert team == "ILS-343"
    assert team is not None and team.is_code

    board = extract_id_from_url(f"https://ru.yougile.com/board/{BOARD}#ILS-343")
    assert board == "ILS-343"
    assert board is not None and board.kind == "code"

    api = extract_id_from_url(f"https://yougile.com/api-v2/tasks/{TASK}")
    assert api == TASK
    assert api is not None and api.is_id

    bare = extract_id_from_url(TASK)
    assert bare == TASK
    assert bare is not None and bare.is_id


def test_parse_task_url() -> None:
    assert parse_task_url(f"https://ru.yougile.com/board/{BOARD}#SAI-515") == TaskRef(
        board_id=BOARD, task_code="SAI-515"
    )
    assert parse_task_url(f"https://ru.yougile.com/board/{BOARD}#sticker-{STICKER}") == TaskRef(
        board_id=BOARD, sticker_id=STICKER
    )
    assert parse_task_url(f"https://ru.yougile.com/board/{BOARD}") == TaskRef(board_id=BOARD)
    assert parse_task_url("SAI-515") is None


def test_resolve_passes_ids_through(client: YouGileClient) -> None:
    assert resolve_project_id(client, BOARD) == BOARD
    assert resolve_board_id(client, f"https://ru.yougile.com/board/{BOARD}") == BOARD
    # Якорь задачи не мешает узнать доску по той же ссылке.
    assert resolve_board_id(client, f"https://ru.yougile.com/board/{BOARD}#SAI-515") == BOARD


def test_resolve_project_by_name(api: respx.MockRouter, client: YouGileClient, paged: Any) -> None:
    route = api.get("/api-v2/projects").respond(json=paged([{"id": "p1", "title": "Ремонт"}]))
    assert resolve_project_id(client, "Ремонт") == "p1"
    assert route.calls.last.request.url.params["title"] == "Ремонт"


def test_resolve_board_scoped_by_project(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    route = api.get("/api-v2/boards").respond(json=paged([{"id": "b1", "title": "Доска"}]))
    assert resolve_board_id(client, "Доска", project_id="p1") == "b1"
    assert route.calls.last.request.url.params["projectId"] == "p1"


def test_resolve_column_scoped_by_board(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    route = api.get("/api-v2/columns").respond(json=paged([{"id": "c1", "title": "В работе"}]))
    assert resolve_column_id(client, "В работе", board_id=BOARD) == "c1"
    assert route.calls.last.request.url.params["boardId"] == BOARD


def test_resolve_not_found(api: respx.MockRouter, client: YouGileClient, paged: Any) -> None:
    api.get("/api-v2/projects").respond(json=paged([]))
    with pytest.raises(ResolveError):
        resolve_project_id(client, "Нет такого")


def test_resolve_fallback_scan_is_bounded(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    """Промах точного фильтра не должен выкачивать всю компанию страница за страницей."""
    big_page = paged(
        [
            {"id": f"{i:08d}-1111-4111-8111-111111111111", "title": f"Задача {i}"}
            for i in range(1000)
        ],
        count=100000,
        next_page=True,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if "title" in request.url.params:
            return httpx.Response(200, json=paged([]))
        return httpx.Response(200, json=big_page)

    route = api.get("/api-v2/task-list").mock(side_effect=handler)
    with pytest.raises(ResolveError):
        resolve_task_id(client, "Несуществующая задача")
    assert route.call_count <= 4


def test_resolve_ambiguous_lists_candidates(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    api.get("/api-v2/projects").respond(
        json=paged([{"id": "p1", "title": "Ремонт офиса"}, {"id": "p2", "title": "Ремонт цеха"}])
    )
    with pytest.raises(AmbiguousNameError) as excinfo:
        resolve_project_id(client, "Ремонт")
    assert excinfo.value.exit_code == 2
    assert {c["id"] for c in excinfo.value.candidates} == {"p1", "p2"}


def test_resolve_prefers_exact_match(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    api.get("/api-v2/projects").respond(
        json=paged([{"id": "p1", "title": "Ремонт"}, {"id": "p2", "title": "Ремонт цеха"}])
    )
    assert resolve_project_id(client, "Ремонт") == "p1"


def test_resolve_user_me(api: respx.MockRouter, client: YouGileClient) -> None:
    api.get("/api-v2/users/me").respond(json={"id": "u-me", "email": "ivan@example.com"})
    assert resolve_user_id(client, "@me") == "u-me"
    assert resolve_user_id(client, "@ME") == "u-me"


def test_resolve_user_me_without_id(api: respx.MockRouter, client: YouGileClient) -> None:
    api.get("/api-v2/users/me").respond(json={})
    with pytest.raises(ResolveError):
        resolve_user_id(client, "@me")


def test_resolve_user_by_email(api: respx.MockRouter, client: YouGileClient, paged: Any) -> None:
    route = api.get("/api-v2/users").respond(
        json=paged([{"id": "u1", "email": "ivan@example.com", "realName": "Иван"}])
    )
    assert resolve_user_id(client, "ivan@example.com") == "u1"
    assert route.calls.last.request.url.params["email"] == "ivan@example.com"
    assert resolve_user_id(client, "Иван") == "u1"


def test_resolve_user_ambiguous(api: respx.MockRouter, client: YouGileClient, paged: Any) -> None:
    api.get("/api-v2/users").respond(
        json=paged(
            [
                {"id": "u1", "email": "a@x.ru", "realName": "Иван Петров"},
                {"id": "u2", "email": "b@x.ru", "realName": "Иван Сидоров"},
            ]
        )
    )
    with pytest.raises(AmbiguousNameError):
        resolve_user_id(client, "Иван")


def test_resolve_task_by_title(api: respx.MockRouter, client: YouGileClient, paged: Any) -> None:
    route = api.get("/api-v2/task-list").respond(json=paged([{"id": "t1", "title": "Починить"}]))
    assert resolve_task_id(client, "Починить", column_id="c1") == "t1"
    assert route.calls.last.request.url.params["columnId"] == "c1"


def test_resolve_task_from_board_url_with_code(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    api.get("/api-v2/columns").respond(json=paged([{"id": "c1"}, {"id": "c2"}]))
    api.get("/api-v2/task-list").mock(
        side_effect=[
            httpx.Response(200, json=paged([{"id": "t9", "idTaskProject": "SAI-1"}])),
            httpx.Response(200, json=paged([{"id": "t7", "idTaskProject": "SAI-515"}])),
        ]
    )
    assert resolve_task_id(client, f"https://ru.yougile.com/board/{BOARD}#SAI-515") == "t7"


def test_resolve_task_from_bare_code_needs_board(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    api.get("/api-v2/columns").respond(json=paged([{"id": "c1"}]))
    api.get("/api-v2/task-list").respond(json=paged([{"id": "t7", "idTaskProject": "SAI-515"}]))
    assert resolve_task_id(client, "SAI-515", board_id=BOARD) == "t7"


def test_resolve_task_code_not_found(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    api.get("/api-v2/columns").respond(json=paged([{"id": "c1"}]))
    api.get("/api-v2/task-list").respond(json=paged([{"id": "t7", "idTaskProject": "1"}]))
    with pytest.raises(ResolveError):
        resolve_task_id(client, f"https://ru.yougile.com/board/{BOARD}#SAI-515")


def test_resolve_task_from_sticker_url_is_rejected(client: YouGileClient) -> None:
    with pytest.raises(ResolveError):
        resolve_task_id(client, f"https://ru.yougile.com/board/{BOARD}#sticker-{STICKER}")


def test_resolve_task_url_with_uuid_fragment(client: YouGileClient) -> None:
    assert resolve_task_id(client, f"https://ru.yougile.com/board/{BOARD}#{TASK}") == TASK


def test_empty_values_are_rejected(client: YouGileClient) -> None:
    for func in (resolve_project_id, resolve_task_id, resolve_user_id):
        with pytest.raises(ResolveError):
            func(client, "  ")


def test_parse_kv_options_keeps_strings() -> None:
    parsed = parse_kv_options(["title=Задача", "count=5", "flag=true"])
    assert parsed == {"title": "Задача", "count": "5", "flag": "true"}


def test_parse_kv_options_typed_and_repeats() -> None:
    assert parse_kv_options(["count=5"], typed=True) == {"count": 5}
    assert parse_kv_options(["a=1", "a=2"]) == {"a": ["1", "2"]}
    assert parse_kv_options(["a[]=1"]) == {"a": ["1"]}


def test_parse_kv_options_requires_equals() -> None:
    with pytest.raises(ValidationError):
        parse_kv_options(["broken"])


def test_parse_field_pairs_types_values() -> None:
    parsed = parse_field_pairs(
        ["done=true", "missing=null", "count=5", "ratio=1.5", 'tags=["a"]', "text=просто"]
    )
    assert parsed == {
        "done": True,
        "missing": None,
        "count": 5,
        "ratio": 1.5,
        "tags": ["a"],
        "text": "просто",
    }


def test_parse_field_pairs_reads_file(tmp_path: Path) -> None:
    body = tmp_path / "body.md"
    body.write_text("# Описание", encoding="utf-8")
    assert parse_field_pairs(["description=@body.md"], base_dir=tmp_path) == {
        "description": "# Описание"
    }


def test_parse_field_pairs_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        parse_field_pairs(["description=@nope.md"], base_dir=tmp_path)


# --------------------------------------------------- код задачи и его кэш (№8)


def _tasks(*codes: str) -> list[dict[str, Any]]:
    return [{"id": f"t{i}", "idTaskProject": code} for i, code in enumerate(codes)]


def test_resolve_task_code_walks_the_whole_list(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    api.get("/api-v2/task-list").mock(
        side_effect=[
            httpx.Response(200, json=paged(_tasks("ABC-1"), next_page=True)),
            httpx.Response(200, json=paged([{"id": "t7", "idTaskProject": "ILS-343"}])),
        ]
    )
    assert resolve_task_code(client, "ils-343") == "t7"


def test_task_code_with_a_wrong_prefix_never_hits_another_task(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    """«XXX-343» не должен резолвиться в задачу, у которой idTaskCommon == 343."""
    api.get("/api-v2/task-list").respond(
        json=paged(
            [
                {"id": "t1", "idTaskProject": "ILS-343", "idTaskCommon": "1201"},
                {"id": "t2", "idTaskProject": "ILS-12", "idTaskCommon": "343"},
            ]
        )
    )
    with pytest.raises(ResolveError):
        resolve_task_code(client, "XXX-343")


def test_task_code_prefers_the_project_code_over_the_common_counter(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    api.get("/api-v2/task-list").respond(
        json=paged(
            [
                {"id": "t1", "idTaskProject": "ILS-343", "idTaskCommon": "1201"},
                {"id": "t2", "idTaskProject": "ILS-12", "idTaskCommon": "343"},
            ]
        )
    )
    assert resolve_task_code(client, "ILS-343") == "t1"
    assert resolve_task_code(client, "343") == "t2"


def test_task_code_from_a_link_matches_the_full_code_only(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    """Обход доски по ссылке не должен цепляться за совпадение одного номера."""
    api.get("/api-v2/columns").respond(json={"content": [{"id": "c1"}]})
    api.get("/api-v2/task-list").respond(
        json=paged(
            [
                {"id": "t2", "idTaskProject": "ILS-12", "idTaskCommon": "343"},
                {"id": "t1", "idTaskProject": "ILS-343", "idTaskCommon": "1201"},
            ]
        )
    )
    assert resolve_task_id(client, f"https://ru.yougile.com/board/{BOARD}#ILS-343") == "t1"


def test_resolve_task_code_reports_a_miss(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    api.get("/api-v2/task-list").respond(json=paged(_tasks("ABC-1")))
    with pytest.raises(ResolveError) as excinfo:
        resolve_task_code(client, "ILS-343")
    assert "Задача «ILS-343» не найдена." in str(excinfo.value)


def test_resolve_task_code_writes_a_private_cache(
    api: respx.MockRouter, client: YouGileClient, paged: Any, isolated_config: Path
) -> None:
    route = api.get("/api-v2/task-list").respond(
        json=paged([{"id": "t7", "idTaskProject": "ILS-343"}])
    )
    assert resolve_task_code(client, "ILS-343") == "t7"
    path = task_cache_path(client.host, account_tag(client.api_key))
    assert path.parent == isolated_config / "cache"
    assert path.name.startswith("tasks-yougile.com-")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["codes"]["ILS-343"] == "t7"

    # Второй раз ходить по всем 1437 задачам нельзя.
    assert resolve_task_code(client, "ILS-343") == "t7"
    assert route.call_count == 1


def test_stale_task_cache_is_ignored(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    path = task_cache_path(client.host, account_tag(client.api_key))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "host": client.host,
                "updated": time.time() - TASK_CACHE_TTL - 1,
                "codes": {"ILS-343": "устарело"},
            }
        ),
        encoding="utf-8",
    )
    api.get("/api-v2/task-list").respond(json=paged([{"id": "t7", "idTaskProject": "ILS-343"}]))
    assert resolve_task_code(client, "ILS-343") == "t7"


def test_broken_task_cache_is_ignored(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    path = task_cache_path(client.host, account_tag(client.api_key))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{не json", encoding="utf-8")
    api.get("/api-v2/task-list").respond(json=paged([{"id": "t7", "idTaskProject": "ILS-343"}]))
    assert resolve_task_code(client, "ILS-343") == "t7"


def test_resolve_task_id_accepts_a_bare_code(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    api.get("/api-v2/task-list").respond(json=paged([{"id": "t7", "idTaskProject": "ILS-343"}]))
    assert resolve_task_id(client, "ILS-343") == "t7"


def test_resolve_task_id_accepts_an_interface_link(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    """Основной сценарий: человеку прислали ссылку из интерфейса."""
    api.get("/api-v2/task-list").respond(json=paged([{"id": "t7", "idTaskProject": "ILS-343"}]))
    assert resolve_task_id(client, "https://ru.yougile.com/team/a1b2c3d4e5f6/#ILS-343") == "t7"


def test_resolve_task_id_falls_back_to_the_title(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    """«Спринт-2» выглядит как код, но может быть названием задачи."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("title") == "Спринт-2":
            return httpx.Response(200, json=paged([{"id": "t3", "title": "Спринт-2"}]))
        return httpx.Response(200, json=paged([{"id": "t7", "idTaskProject": "ILS-343"}]))

    api.get("/api-v2/task-list").mock(side_effect=handler)
    assert resolve_task_id(client, "Спринт-2") == "t3"


# ------------------------------------------------------- согласование рода (№3)


def test_not_found_messages_agree_in_gender(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    api.get("/api-v2/boards").respond(json=paged([]))
    with pytest.raises(ResolveError) as excinfo:
        resolve_board_id(client, "нет-такой-доски")
    assert str(excinfo.value) == "Доска «нет-такой-доски» не найдена."

    api.get("/api-v2/projects").respond(json=paged([]))
    with pytest.raises(ResolveError) as excinfo:
        resolve_project_id(client, "нет-такого")
    assert str(excinfo.value) == "Проект «нет-такого» не найден."


def test_ambiguous_message_uses_the_genitive_plural(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    api.get("/api-v2/boards").respond(
        json=paged([{"id": "b1", "title": "Доска раз"}, {"id": "b2", "title": "Доска два"}])
    )
    with pytest.raises(AmbiguousNameError) as excinfo:
        resolve_board_id(client, "Доска")
    assert "Найдено несколько (2) досок с именем «Доска»." in str(excinfo.value)


def test_missing_value_messages_agree_in_gender(client: YouGileClient) -> None:
    with pytest.raises(ResolveError) as excinfo:
        resolve_task_id(client, "   ")
    assert str(excinfo.value) == "Не указана задача."
    with pytest.raises(ResolveError) as excinfo:
        resolve_column_id(client, "")
    assert str(excinfo.value) == "Не указана колонка."


def test_task_cache_is_private_to_the_account(
    api: respx.MockRouter, paged: Any, isolated_config: Path
) -> None:
    """Коды задач принадлежат компании: второй ключ на том же хосте не берёт чужой кэш."""

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers.get("Authorization", "")
        task = "task-a" if key.endswith("key-a") else "task-b"
        return httpx.Response(200, json=paged([{"id": task, "idTaskProject": "ILS-1"}]))

    api.get("/api-v2/task-list").mock(side_effect=handler)

    with YouGileClient(api_key="key-a", base_url="https://yougile.com") as first:
        assert resolve_task_code(first, "ILS-1") == "task-a"
    with YouGileClient(api_key="key-b", base_url="https://yougile.com") as second:
        assert resolve_task_code(second, "ILS-1") == "task-b"

    cache = isolated_config / "cache"
    assert len(sorted(cache.glob("tasks-yougile.com-*.json"))) == 2
    assert account_tag("key-a") != account_tag("key-b")
