"""Tests for `yougile task …`.

Everything goes through the real Typer app via the ``run`` fixture; the network
is mocked with respx and the config directory is a tmp_path (see conftest).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response

from yougile_cli.commands import tasks as tasks_module

TASK_ID = "aaaaaaaa-1111-4111-8111-111111111111"
OTHER_TASK_ID = "bbbbbbbb-2222-4222-8222-222222222222"
COLUMN_ID = "cccccccc-3333-4333-8333-333333333333"
BOARD_ID = "dddddddd-4444-4444-8444-444444444444"
USER_ID = "eeeeeeee-5555-4555-8555-555555555555"
OTHER_USER_ID = "ffffffff-6666-4666-8666-666666666666"


def task_payload(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": TASK_ID,
        "title": "Починить кран",
        "columnId": COLUMN_ID,
        "completed": False,
        "archived": False,
        "assigned": [USER_ID],
        "idTaskProject": "SAI-515",
        "timestamp": 1700000000000,
        "deadline": {"deadline": 1700000000000, "withTime": False},
    }
    data.update(overrides)
    return data


def body_of(route: respx.Route) -> Any:
    return json.loads(route.calls.last.request.content)


def params_of(route: respx.Route) -> dict[str, str]:
    return dict(route.calls.last.request.url.params)


# --------------------------------------------------------------------------- list


def test_list_shows_gh_columns(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get("/api-v2/task-list").respond(json=paged([task_payload()]))
    result = run("task list")
    assert result.exit_code == 0, result.output
    assert "TITLE" in result.stdout
    assert "STATE" in result.stdout
    assert "DEADLINE" in result.stdout
    assert "Починить кран" in result.stdout
    assert "open" in result.stdout


def test_list_defaults_to_open_tasks(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get("/api-v2/task-list").respond(
        json=paged(
            [
                task_payload(),
                task_payload(id=OTHER_TASK_ID, title="Уже сделано", completed=True),
            ]
        )
    )
    result = run("task list")
    assert result.exit_code == 0, result.output
    assert "Починить кран" in result.stdout
    assert "Уже сделано" not in result.stdout


def test_list_state_closed(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get("/api-v2/task-list").respond(
        json=paged(
            [
                task_payload(),
                task_payload(id=OTHER_TASK_ID, title="Уже сделано", completed=True),
            ]
        )
    )
    result = run("task list --state closed")
    assert result.exit_code == 0, result.output
    assert "Уже сделано" in result.stdout
    assert "Починить кран" not in result.stdout


def test_list_limit(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get("/api-v2/task-list").respond(
        json=paged([task_payload(id=f"{index}", title=f"Задача {index}") for index in range(5)])
    )
    result = run("task list -L 2")
    assert result.exit_code == 0, result.output
    assert "Задача 0" in result.stdout
    assert "Задача 2" not in result.stdout


def test_list_assignee_resolved_by_email(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get("/api-v2/users").respond(
        json=paged([{"id": USER_ID, "email": "ivan@example.com", "realName": "Иван"}])
    )
    route = api.get("/api-v2/task-list").respond(json=paged([task_payload()]))
    result = run("task list --assignee ivan@example.com")
    assert result.exit_code == 0, result.output
    assert params_of(route)["assignedTo"] == USER_ID


def test_list_board_expands_into_columns(run: Any, api: respx.MockRouter, paged: Any) -> None:
    columns = api.get("/api-v2/columns").respond(
        json=paged([{"id": COLUMN_ID, "title": "В работе", "boardId": BOARD_ID}])
    )
    route = api.get("/api-v2/task-list").respond(json=paged([task_payload()]))
    result = run(["task", "list", "--board", BOARD_ID])
    assert result.exit_code == 0, result.output
    assert params_of(columns)["boardId"] == BOARD_ID
    assert params_of(route)["columnId"] == COLUMN_ID


def test_list_search_and_sticker_filters(run: Any, api: respx.MockRouter, paged: Any) -> None:
    route = api.get("/api-v2/task-list").respond(json=paged([task_payload()]))
    result = run(["task", "list", "--search", "кран", "--sticker", "s1", "--include-deleted"])
    assert result.exit_code == 0, result.output
    query = params_of(route)
    assert query["title"] == "кран"
    assert query["stickerId"] == "s1"
    assert query["includeDeleted"] == "true"


def test_list_search_short_flag(run: Any, api: respx.MockRouter, paged: Any) -> None:
    """`-S` — общая короткая форма --search во всех списках."""
    route = api.get("/api-v2/task-list").respond(json=paged([task_payload()]))
    result = run(["task", "list", "-S", "кран"])
    assert result.exit_code == 0, result.output
    assert params_of(route)["title"] == "кран"


def test_list_json_selects_fields(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get("/api-v2/task-list").respond(json=paged([task_payload()]))
    result = run("task list --json id,title")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"id": TASK_ID, "title": "Починить кран"}]


def test_list_json_without_fields_lists_them(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get("/api-v2/task-list").respond(json=paged([task_payload()]))
    result = run(["task", "list", "--json", ""])
    assert result.exit_code == 1
    assert "доступные поля" in result.output


def test_list_bare_json_flag_lists_fields(run: Any, api: respx.MockRouter, paged: Any) -> None:
    """gh parity: `--json` with no value at all, not just `--json ""`."""
    api.get("/api-v2/task-list").respond(json=paged([task_payload()]))
    result = run(["task", "list", "--json"])
    assert result.exit_code == 1
    assert "доступные поля" in result.output


def test_list_full_ids(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get("/api-v2/task-list").respond(json=paged([task_payload()]))
    short = run("task list")
    full = run("task list --full-ids")
    assert TASK_ID not in short.stdout
    assert TASK_ID in full.stdout


# --------------------------------------------------------------------------- view


def test_view(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload())
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(json=paged([]))
    result = run(["task", "view", TASK_ID])
    assert result.exit_code == 0, result.output
    assert "Починить кран" in result.stdout
    assert "open" in result.stdout


def test_view_shortens_every_assignee(run: Any, api: respx.MockRouter, paged: Any) -> None:
    """Один исполнитель сокращался, двое — нет: строка спорила сама с собой."""
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(
        json=task_payload(assigned=[USER_ID, OTHER_USER_ID])
    )
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(json=paged([]))

    result = run(["task", "view", TASK_ID])
    assert result.exit_code == 0, result.output
    assert USER_ID not in result.stdout
    assert OTHER_USER_ID not in result.stdout
    assert "eeeeeeee, ffffffff" in result.stdout

    full = run(["task", "view", TASK_ID, "--full-ids"])
    assert OTHER_USER_ID in full.stdout


def test_view_resolves_title_to_id(run: Any, api: respx.MockRouter, paged: Any) -> None:
    listing = api.get("/api-v2/task-list").respond(
        json=paged([{"id": TASK_ID, "title": "Починить кран"}])
    )
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload())
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(json=paged([]))
    result = run(["task", "view", "Починить кран"])
    assert result.exit_code == 0, result.output
    assert params_of(listing)["title"] == "Починить кран"


def test_view_comments(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload())
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(
        json=paged([{"id": 7, "fromUserId": USER_ID, "text": "Уже чиню"}])
    )
    result = run(["task", "view", TASK_ID, "--comments"])
    assert result.exit_code == 0, result.output
    assert "Уже чиню" in result.stdout


def test_view_comments_limit_zero_fetches_everything(
    run: Any, api: respx.MockRouter, paged: Any
) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload())
    messages = api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(
        json=paged([{"id": n, "fromUserId": USER_ID, "text": f"м{n}"} for n in range(50)])
    )
    result = run(["task", "view", TASK_ID, "--comments", "-L", "0", "-o", "json"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)["comments"]) == 50
    assert messages.called


def test_view_no_browser_prints_url(run: Any, api: respx.MockRouter) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload())
    api.get(f"/api-v2/columns/{COLUMN_ID}").respond(
        json={"id": COLUMN_ID, "title": "В работе", "boardId": BOARD_ID}
    )
    result = run(["task", "view", TASK_ID, "--no-browser"])
    assert result.exit_code == 0, result.output
    assert f"https://yougile.com/board/{BOARD_ID}#SAI-515" in result.stdout


def test_view_web_launches_browser(
    run: Any, api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload())
    api.get(f"/api-v2/columns/{COLUMN_ID}").respond(json={"id": COLUMN_ID, "boardId": BOARD_ID})
    opened: list[str] = []
    monkeypatch.setattr(tasks_module.typer, "launch", opened.append)
    result = run(["task", "view", TASK_ID, "--web"])
    assert result.exit_code == 0, result.output
    assert opened == [f"https://yougile.com/board/{BOARD_ID}#SAI-515"]


# --------------------------------------------------------------------------- create


def test_create_prints_url(run: Any, api: respx.MockRouter) -> None:
    route = api.post("/api-v2/tasks").mock(return_value=Response(201, json={"id": TASK_ID}))
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload())
    api.get(f"/api-v2/columns/{COLUMN_ID}").respond(json={"id": COLUMN_ID, "boardId": BOARD_ID})
    result = run(["task", "create", "Починить кран", "--column", COLUMN_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"title": "Починить кран", "columnId": COLUMN_ID}
    assert f"https://yougile.com/board/{BOARD_ID}#SAI-515" in result.stdout


def test_create_full_payload(run: Any, api: respx.MockRouter) -> None:
    route = api.post("/api-v2/tasks").mock(return_value=Response(201, json={"id": TASK_ID}))
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(columnId=None))
    result = run(
        [
            "task",
            "create",
            "--title",
            "Задача",
            "--body",
            "Описание",
            "--assignee",
            USER_ID,
            "--deadline",
            "2030-01-02",
            "--color",
            "red",
            "--plan-hours",
            "3",
            "--checklist",
            "Шаги:раз,два",
            "--completed",
        ]
    )
    assert result.exit_code == 0, result.output
    sent = body_of(route)
    assert sent["title"] == "Задача"
    assert sent["description"] == "Описание"
    assert sent["assigned"] == [USER_ID]
    assert sent["color"] == "task-red"
    assert sent["completed"] is True
    assert sent["timeTracking"] == {"plan": 3.0, "work": 0}
    assert sent["deadline"]["withTime"] is False
    # Pinned to an independently computed epoch: the wall clock the user typed is local.
    assert sent["deadline"]["deadline"] == int(datetime(2030, 1, 2).timestamp() * 1000)
    assert sent["checklists"] == [
        {
            "title": "Шаги",
            "items": [
                {"title": "раз", "isCompleted": False},
                {"title": "два", "isCompleted": False},
            ],
        }
    ]


def test_create_body_file(run: Any, api: respx.MockRouter, tmp_path: Path) -> None:
    note = tmp_path / "body.md"
    note.write_text("Из файла", encoding="utf-8")
    route = api.post("/api-v2/tasks").mock(return_value=Response(201, json={"id": TASK_ID}))
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(columnId=None))
    result = run(["task", "create", "Задача", "--body-file", str(note)])
    assert result.exit_code == 0, result.output
    assert body_of(route)["description"] == "Из файла"


def test_create_editor(run: Any, api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_module, "_is_tty", lambda *_a: True)
    monkeypatch.setattr(tasks_module, "_open_editor", lambda initial="": "Из редактора")
    route = api.post("/api-v2/tasks").mock(return_value=Response(201, json={"id": TASK_ID}))
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(columnId=None))
    result = run(["task", "create", "Задача", "--editor"])
    assert result.exit_code == 0, result.output
    assert body_of(route)["description"] == "Из редактора"


def test_create_editor_refused_without_prompts(
    run: Any, api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """$EDITOR — самый интерактивный вопрос: без tty его открывать нельзя."""
    launched: list[str] = []
    monkeypatch.setattr(tasks_module, "_open_editor", lambda initial="": launched.append(initial))
    result = run(["task", "create", "Задача", "--editor"])
    assert result.exit_code == 2, result.output
    assert not launched


def test_create_without_title_is_usage_error(run: Any, api: respx.MockRouter) -> None:
    result = run("task create")
    assert result.exit_code == 2
    assert "заголовок" in result.output.lower()


def test_create_rejects_two_body_sources(run: Any, api: respx.MockRouter) -> None:
    result = run(["task", "create", "Задача", "--body", "a", "--editor"])
    assert result.exit_code == 2


# --------------------------------------------------------------------------- edit


def test_edit(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "edit", TASK_ID, "--title", "Новый", "--body", "Текст"])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"title": "Новый", "description": "Текст"}
    assert "✓" in result.output


def test_create_deadline_carries_required_arrays(run: Any, api: respx.MockRouter) -> None:
    route = api.post("/api-v2/tasks").mock(return_value=Response(201, json={"id": TASK_ID}))
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(columnId=None))
    result = run(["task", "create", "Задача", "--deadline", "2030-01-02"])
    assert result.exit_code == 0, result.output
    sent = body_of(route)["deadline"]
    assert sent["blockedPoints"] == []
    assert sent["links"] == []


def test_edit_start_date_keeps_existing_deadline(run: Any, api: respx.MockRouter) -> None:
    """PUT replaces the whole deadline object, so the stored keys must be merged in."""
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(
        json=task_payload(deadline={"deadline": 1767214800000, "withTime": True, "history": []})
    )
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "edit", TASK_ID, "--start-date", "2030-01-05"])
    assert result.exit_code == 0, result.output
    sent = body_of(route)["deadline"]
    assert sent["deadline"] == 1767214800000
    assert sent["withTime"] is True
    assert sent["history"] == []
    assert sent["startDate"] > 0


def test_edit_clear_deadline_and_undelete(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "edit", TASK_ID, "--clear-deadline", "--undelete"])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"deadline": {"deleted": True}, "deleted": False}


def test_edit_moves_to_column(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "edit", TASK_ID, "--column", COLUMN_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"columnId": COLUMN_ID}


def test_short_b_means_board_everywhere_in_the_task_group(
    run: Any, api: respx.MockRouter, paged: Any
) -> None:
    """`-b` scopes the board; it must never silently overwrite the description."""
    api.get("/api-v2/boards").respond(json=paged([{"id": BOARD_ID, "title": "Разработка"}]))
    api.get("/api-v2/columns").respond(
        json=paged([{"id": COLUMN_ID, "title": "В работе", "boardId": BOARD_ID}])
    )
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "edit", TASK_ID, "-b", "Разработка", "-c", "В работе"])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"columnId": COLUMN_ID}


def test_edit_without_fields_is_usage_error(run: Any, api: respx.MockRouter) -> None:
    result = run(["task", "edit", TASK_ID])
    assert result.exit_code == 2


def test_move_supports_json_and_jq(run: Any, api: respx.MockRouter) -> None:
    """gh-spec §4: a mutation must let a script pull the id out."""
    api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "move", TASK_ID, COLUMN_ID, "--json", "id"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"id": TASK_ID}]

    result = run(["task", "close", TASK_ID, "--jq", ".id"])
    assert result.exit_code == 0, result.output
    assert TASK_ID in result.stdout


# --------------------------------------------------------------------------- state


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("close", {"completed": True}),
        ("reopen", {"completed": False}),
        ("archive", {"archived": True}),
        ("unarchive", {"archived": False}),
    ],
)
def test_state_commands(
    run: Any, api: respx.MockRouter, command: str, expected: dict[str, Any]
) -> None:
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", command, TASK_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == expected


def test_delete_is_a_put_with_deleted_true(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "delete", TASK_ID, "--yes"])
    assert result.exit_code == 0, result.output
    assert route.calls.last.request.method == "PUT"
    assert body_of(route) == {"deleted": True}


def test_delete_without_yes_needs_confirmation(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "delete", TASK_ID])
    assert result.exit_code == 2
    assert not route.called


def test_move(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "move", TASK_ID, COLUMN_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"columnId": COLUMN_ID}


# --------------------------------------------------------------------------- assignees


def test_assign_appends_to_current(run: Any, api: respx.MockRouter) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload())
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "assign", TASK_ID, OTHER_USER_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"assigned": [USER_ID, OTHER_USER_ID]}


def test_unassign_removes(run: Any, api: respx.MockRouter) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload())
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "unassign", TASK_ID, USER_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"assigned": []}


def test_assign_without_users_is_usage_error(run: Any, api: respx.MockRouter) -> None:
    result = run(["task", "assign", TASK_ID])
    assert result.exit_code == 2


# --------------------------------------------------------------------------- comment


def test_comment(run: Any, api: respx.MockRouter) -> None:
    route = api.post(f"/api-v2/chats/{TASK_ID}/messages").mock(
        return_value=Response(201, json={"id": 42})
    )
    result = run(["task", "comment", TASK_ID, "Готово"])
    assert result.exit_code == 0, result.output
    assert body_of(route)["text"] == "Готово"


def test_comment_from_body_file(run: Any, api: respx.MockRouter, tmp_path: Path) -> None:
    note = tmp_path / "comment.txt"
    note.write_text("Из файла", encoding="utf-8")
    route = api.post(f"/api-v2/chats/{TASK_ID}/messages").mock(
        return_value=Response(201, json={"id": 42})
    )
    result = run(["task", "comment", TASK_ID, "--body-file", str(note)])
    assert result.exit_code == 0, result.output
    assert body_of(route)["text"] == "Из файла"


def test_comment_without_text_is_usage_error(run: Any, api: respx.MockRouter) -> None:
    result = run(["task", "comment", TASK_ID])
    assert result.exit_code == 2


# --------------------------------------------------------------------------- subscribers


def test_subscribers_list(run: Any, api: respx.MockRouter) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}/chat-subscribers").respond(json=[USER_ID])
    result = run(["task", "subscribers", "list", TASK_ID, "--full-ids"])
    assert result.exit_code == 0, result.output
    assert USER_ID in result.stdout


def test_subscribers_add(run: Any, api: respx.MockRouter) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}/chat-subscribers").respond(json=[USER_ID])
    route = api.put(f"/api-v2/tasks/{TASK_ID}/chat-subscribers").respond(json={"id": TASK_ID})
    result = run(["task", "subscribers", "add", TASK_ID, OTHER_USER_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"content": [USER_ID, OTHER_USER_ID]}


def test_subscribers_remove(run: Any, api: respx.MockRouter) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}/chat-subscribers").respond(json=[USER_ID, OTHER_USER_ID])
    route = api.put(f"/api-v2/tasks/{TASK_ID}/chat-subscribers").respond(json={"id": TASK_ID})
    result = run(["task", "subscribers", "remove", TASK_ID, USER_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"content": [OTHER_USER_ID]}


def test_subscribers_set(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"/api-v2/tasks/{TASK_ID}/chat-subscribers").respond(json={"id": TASK_ID})
    result = run(["task", "subscribers", "set", TASK_ID, USER_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"content": [USER_ID]}


# --------------------------------------------------------------------------- errors


def test_unknown_task_title_fails_with_exit_1(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get("/api-v2/task-list").respond(json=paged([]))
    result = run(["task", "view", "Нет такой задачи"])
    assert result.exit_code == 1
    assert "ошибка" in result.output


def test_api_error_is_reported(run: Any, api: respx.MockRouter) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(404, json={"message": "Not found"})
    result = run(["task", "view", TASK_ID])
    assert result.exit_code == 1
    assert "ошибка" in result.output


def test_without_token_exits_4(run: Any, api: respx.MockRouter) -> None:
    result = run("task list", token=None)
    assert result.exit_code == 4


# --------------------------------------------------------------------------- helpers


def test_parse_datetime_to_ms_is_local_wall_clock() -> None:
    """Anchored to a literal epoch, so a local-time/UTC mix-up cannot stay green."""
    assert tasks_module.parse_datetime_to_ms("2030-01-02 03:04") == int(
        datetime(2030, 1, 2, 3, 4).timestamp() * 1000
    )
    assert tasks_module.parse_datetime_to_ms("2030-01-02") == int(
        datetime(2030, 1, 2).timestamp() * 1000
    )


def test_parse_datetime_to_ms_and_format_ms() -> None:
    moment = tasks_module.parse_datetime_to_ms("2030-01-02 03:04")
    assert tasks_module.format_ms(moment) == "2030-01-02 03:04"
    assert tasks_module.format_ms(moment, False) == "2030-01-02"
    assert tasks_module.parse_datetime_to_ms(1700000000000) == 1700000000000
    assert tasks_module.datetime_has_time("2030-01-02") is False


def test_parse_datetime_rejects_garbage() -> None:
    from yougile_cli.errors import ValidationError

    with pytest.raises(ValidationError):
        tasks_module.parse_datetime_to_ms("позавчера")


# --------------------------------------------------------------------------- метавары


@pytest.mark.parametrize(
    ("command", "expected", "forbidden"),
    [
        (["task", "create", "--help"], "ЗАГОЛОВОК", "TITLE"),
        (["task", "move", "--help"], "КОЛОНКА", "COLUMN"),
        (["task", "assign", "--help"], "ИСПОЛНИТЕЛЬ", "USER"),
        (["task", "unassign", "--help"], "ИСПОЛНИТЕЛЬ", "USER"),
        (["task", "view", "--help"], "ЗАДАЧА", "TASK"),
        (["task", "attachments", "--help"], "КАТАЛОГ", "DIRECTORY"),
        (["task", "subscribers", "add", "--help"], "СОТРУДНИК", "USER"),
    ],
)
def test_help_metavars_are_russian(
    run: Any, command: list[str], expected: str, forbidden: str
) -> None:
    result = run(command)
    assert result.exit_code == 0, result.output
    assert expected in result.stdout
    assert forbidden not in result.stdout


def test_help_has_no_latin_metavars(run: Any) -> None:
    for command in ("list", "view", "create", "edit", "move", "comment", "attachments"):
        result = run(["task", command, "--help"])
        assert result.exit_code == 0, result.output
        for latin in ("TEXT", "INTEGER", "FLOAT", "PATH", "TITLE", "USER", "FILENAME"):
            assert latin not in result.stdout, f"{command}: {latin}"


# --------------------------------------------------------------------------- позиционные и флаги


def test_create_title_argument_and_flag_conflict_is_usage_error(
    run: Any, api: respx.MockRouter
) -> None:
    route = api.post("/api-v2/tasks").mock(return_value=Response(201, json={"id": TASK_ID}))
    result = run(["task", "create", "Один", "--title", "Другой"])
    assert result.exit_code == 2, result.output
    assert not route.called


def test_create_title_argument_and_flag_agree(run: Any, api: respx.MockRouter) -> None:
    route = api.post("/api-v2/tasks").mock(return_value=Response(201, json={"id": TASK_ID}))
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(columnId=None))
    result = run(["task", "create", "Одно и то же", "--title", "Одно и то же"])
    assert result.exit_code == 0, result.output
    assert body_of(route)["title"] == "Одно и то же"


def test_move_accepts_column_flag(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "move", TASK_ID, "--column", COLUMN_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"columnId": COLUMN_ID}


def test_move_column_conflict_is_usage_error(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "move", TASK_ID, COLUMN_ID, "--column", OTHER_TASK_ID])
    assert result.exit_code == 2, result.output
    assert not route.called


def test_move_without_column_is_usage_error(run: Any, api: respx.MockRouter) -> None:
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "move", TASK_ID])
    assert result.exit_code == 2, result.output
    assert "Не указана колонка" in result.output
    assert not route.called


def test_assign_accepts_assignee_flag(run: Any, api: respx.MockRouter) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(assigned=[]))
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "assign", TASK_ID, "--assignee", USER_ID, "-a", OTHER_USER_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"assigned": [USER_ID, OTHER_USER_ID]}


def test_assign_merges_argument_and_flag(run: Any, api: respx.MockRouter) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(assigned=[]))
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "assign", TASK_ID, USER_ID, "--assignee", OTHER_USER_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"assigned": [USER_ID, OTHER_USER_ID]}


def test_unassign_accepts_assignee_flag(run: Any, api: respx.MockRouter) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(assigned=[USER_ID]))
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "unassign", TASK_ID, "--assignee", USER_ID])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"assigned": []}


# --------------------------------------------------------------------------- код и ссылки


def test_view_accepts_bare_task_code(run: Any, api: respx.MockRouter, paged: Any) -> None:
    listing = api.get("/api-v2/task-list").respond(json=paged([task_payload()]))
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload())
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(json=paged([]))
    result = run(["task", "view", "SAI-515"])
    assert result.exit_code == 0, result.output
    assert listing.called
    assert "Починить кран" in result.stdout


def test_close_accepts_team_url_with_task_code(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get("/api-v2/task-list").respond(json=paged([task_payload()]))
    route = api.put(f"/api-v2/tasks/{TASK_ID}").respond(json={"id": TASK_ID})
    result = run(["task", "close", "https://ru.yougile.com/team/a1b2c3d4e5f6/#SAI-515"])
    assert result.exit_code == 0, result.output
    assert body_of(route) == {"completed": True}


def test_comment_accepts_board_url_with_task_code(
    run: Any, api: respx.MockRouter, paged: Any
) -> None:
    api.get("/api-v2/columns").respond(json=paged([{"id": COLUMN_ID, "boardId": BOARD_ID}]))
    api.get("/api-v2/task-list").respond(json=paged([task_payload()]))
    route = api.post(f"/api-v2/chats/{TASK_ID}/messages").mock(
        return_value=Response(201, json={"id": 1})
    )
    result = run(["task", "comment", f"https://ru.yougile.com/board/{BOARD_ID}#SAI-515", "Готово"])
    assert result.exit_code == 0, result.output
    assert body_of(route)["text"] == "Готово"


def test_unknown_task_message_agrees_in_gender(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get("/api-v2/task-list").respond(json=paged([]))
    result = run(["task", "view", "Нет такой задачи"])
    assert result.exit_code == 1
    assert "не найдена" in result.output
    assert "Не найден задача" not in result.output


def test_unknown_column_message_agrees_in_gender(
    run: Any, api: respx.MockRouter, paged: Any
) -> None:
    api.get("/api-v2/columns").respond(json=paged([]))
    result = run(["task", "move", TASK_ID, "нет-такой-колонки"])
    assert result.exit_code == 1
    assert "не найдена" in result.output


# --------------------------------------------------------------------------- описание и вложения

DESCRIPTION_HTML = (
    "<p>Первая строка</p><ul><li>раз</li><li>два</li></ul>"
    '<p><img src="/user-data/aaa/IMG_1.jpg"></p>'
)
CHAT_FILE_MESSAGE = "/root/#file:%2Fuser-data%2Fbbb%2Fdoc.pdf"
CHAT_PREVIEW_MESSAGE = "/root/#file:%2Fuser-data%2Fbbb%2Fdoc.pdf%3Fpreviews%5B%5D%3D480x480"


def test_view_renders_description_as_text(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(description=DESCRIPTION_HTML))
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(json=paged([]))
    result = run(["task", "view", TASK_ID])
    assert result.exit_code == 0, result.output
    assert "ОПИСАНИЕ" in result.stdout
    assert "Первая строка" in result.stdout
    assert "• раз" in result.stdout
    assert "<p>" not in result.stdout


def test_view_raw_description_prints_html(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(description=DESCRIPTION_HTML))
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(json=paged([]))
    result = run(["task", "view", TASK_ID, "--raw-description"])
    assert result.exit_code == 0, result.output
    assert "<p>Первая строка</p>" in result.stdout


def test_view_lists_attachments_from_description_and_chat(
    run: Any, api: respx.MockRouter, paged: Any
) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(description=DESCRIPTION_HTML))
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(
        json=paged([{"id": 1, "fromUserId": USER_ID, "text": CHAT_FILE_MESSAGE}])
    )
    result = run(["task", "view", TASK_ID])
    assert result.exit_code == 0, result.output
    assert "ВЛОЖЕНИЯ" in result.stdout
    assert "IMG_1.jpg" in result.stdout
    assert "doc.pdf" in result.stdout
    assert "https://yougile.com/user-data/bbb/doc.pdf" in result.stdout


def test_view_and_attachments_print_the_original_not_the_preview(
    run: Any, api: respx.MockRouter, paged: Any
) -> None:
    """`chat messages` уже отдаёт оригинал; задача не должна показывать превью."""
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(description=""))
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(
        json=paged([{"id": 1, "fromUserId": USER_ID, "text": CHAT_PREVIEW_MESSAGE}])
    )
    view = run(["task", "view", TASK_ID])
    assert view.exit_code == 0, view.output
    assert "previews" not in view.stdout

    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(description=""))
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(
        json=paged([{"id": 1, "fromUserId": USER_ID, "text": CHAT_PREVIEW_MESSAGE}])
    )
    rows = run(["task", "attachments", TASK_ID, "-o", "json"])
    assert rows.exit_code == 0, rows.output
    assert json.loads(rows.stdout)[0]["url"] == "https://yougile.com/user-data/bbb/doc.pdf"


def test_view_json_keeps_raw_description(run: Any, api: respx.MockRouter) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(description=DESCRIPTION_HTML))
    result = run(["task", "view", TASK_ID, "-o", "json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["description"] == DESCRIPTION_HTML


def test_attachments_table(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(description=DESCRIPTION_HTML))
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(
        json=paged([{"id": 1, "fromUserId": USER_ID, "text": CHAT_FILE_MESSAGE}])
    )
    result = run(["task", "attachments", TASK_ID])
    assert result.exit_code == 0, result.output
    assert "ИСТОЧНИК" in result.stdout
    assert "ИМЯ" in result.stdout
    assert "ТИП" in result.stdout
    assert "URL" in result.stdout
    assert "изображение" in result.stdout
    assert "описание" in result.stdout
    assert "чат" in result.stdout


def test_attachments_source_filter_skips_the_chat(
    run: Any, api: respx.MockRouter, paged: Any
) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(description=DESCRIPTION_HTML))
    chat = api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(json=paged([]))
    result = run(["task", "attachments", TASK_ID, "--source", "описание"])
    assert result.exit_code == 0, result.output
    assert "IMG_1.jpg" in result.stdout
    assert not chat.called


def test_attachments_empty_says_so(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(description=""))
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(json=paged([]))
    result = run(["task", "attachments", TASK_ID])
    assert result.exit_code == 0, result.output
    assert "Ничего не найдено" in result.output
    assert result.stdout.strip() == ""


def test_attachments_download(run: Any, api: respx.MockRouter, paged: Any, tmp_path: Path) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(description=DESCRIPTION_HTML))
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(json=paged([]))
    api.get("/user-data/aaa/IMG_1.jpg").mock(return_value=Response(200, content=b"12345"))
    target = tmp_path / "downloads"
    result = run(["task", "attachments", TASK_ID, "--download", "--dir", str(target)])
    assert result.exit_code == 0, result.output
    saved = target / "IMG_1.jpg"
    assert saved.read_bytes() == b"12345"
    assert str(saved) in result.output


def test_attachments_json_has_english_keys(run: Any, api: respx.MockRouter, paged: Any) -> None:
    api.get(f"/api-v2/tasks/{TASK_ID}").respond(json=task_payload(description=DESCRIPTION_HTML))
    api.get(f"/api-v2/chats/{TASK_ID}/messages").respond(json=paged([]))
    result = run(["task", "attachments", TASK_ID, "-o", "json"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)
    assert rows[0]["name"] == "IMG_1.jpg"
    assert rows[0]["source"] == "описание"
    assert rows[0]["url"] == "https://yougile.com/user-data/aaa/IMG_1.jpg"
