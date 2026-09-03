"""Tests for `yougile webhook`."""

from __future__ import annotations

import json
from typing import Any

import pytest

from yougile_cli.commands.webhooks import EVENTS_NOTE, app
from yougile_cli.context import AppContext
from yougile_cli.errors import YouGileError, exit_code_for
from yougile_cli.output import OutputFormat, OutputOptions

HOOK_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
PROJECT_ID = "33333333-3333-4333-8333-333333333333"

HOOK = {
    "id": HOOK_ID,
    "url": "https://webhook.site/first",
    "event": "task-created",
    "disabled": False,
    "lastSuccess": 1700000000000,
    "failuresSinceLastSuccess": 0,
    "filters": [],
}
OTHER = {**HOOK, "id": OTHER_ID, "url": "https://webhook.site/second", "event": "board-moved"}


@pytest.fixture
def run(client: Any, runner: Any) -> Any:
    """Invoke the webhook sub-app with a ready AppContext, the way cli.py does."""

    def _run(
        args: list[str],
        *,
        fmt: str = "json",
        input: str | None = None,
    ) -> tuple[int, str, BaseException | None]:
        app_ctx = AppContext(out=OutputOptions(fmt=OutputFormat(fmt)))
        app_ctx.set_client(client)
        result = runner.invoke(app, args, input=input, obj=app_ctx)
        exc = result.exception
        code = exit_code_for(exc) if isinstance(exc, YouGileError) else result.exit_code
        return code, result.output, exc

    return _run


def body_of(route: Any, index: int = 0) -> Any:
    return json.loads(route.calls[index].request.content)


# --------------------------------------------------------------------------- list


def test_list_webhooks_bare_list(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK, OTHER])
    code, out, _ = run(["list"])
    assert code == 0
    assert [row["id"] for row in json.loads(out)] == [HOOK_ID, OTHER_ID]


def test_list_webhooks_single_object(run: Any, api: Any) -> None:
    """The spec declares one object here; that shape must work too."""
    api.get("/api-v2/webhooks").respond(json=HOOK)
    code, out, _ = run(["list"])
    assert code == 0
    assert json.loads(out) == [HOOK]


def test_list_webhooks_paged_envelope(run: Any, api: Any, paged: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=paged([HOOK]))
    code, out, _ = run(["list"])
    assert code == 0
    assert json.loads(out)[0]["url"] == HOOK["url"]


def test_list_webhooks_limit_and_include_deleted(run: Any, api: Any) -> None:
    route = api.get("/api-v2/webhooks").respond(json=[HOOK, OTHER])
    code, out, _ = run(["list", "--include-deleted", "--limit", "1"])
    assert code == 0
    assert len(json.loads(out)) == 1
    assert route.calls[0].request.url.params["includeDeleted"] == "true"


def test_list_webhooks_json_fields(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK, OTHER])
    code, out, _ = run(["list", "--json", "id,event"], fmt="table")
    assert code == 0
    assert json.loads(out) == [
        {"id": HOOK_ID, "event": "task-created"},
        {"id": OTHER_ID, "event": "board-moved"},
    ]


def test_list_webhooks_unknown_json_field(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK])
    code, _, exc = run(["list", "--json", "nope"], fmt="table")
    assert code == 1
    assert isinstance(exc, YouGileError)


# --------------------------------------------------------------------------- view


def test_view_webhook_by_id(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK, OTHER])
    code, out, _ = run(["view", HOOK_ID])
    assert code == 0
    assert json.loads(out)["url"] == HOOK["url"]


def test_view_webhook_by_url_fragment(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK, OTHER])
    code, out, _ = run(["view", "second"])
    assert code == 0
    assert json.loads(out)["id"] == OTHER_ID


def test_view_webhook_ambiguous(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK, OTHER])
    code, _, exc = run(["view", "webhook.site"])
    assert code == 1
    assert isinstance(exc, YouGileError)


def test_view_webhook_not_found(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK])
    code, _, exc = run(["view", "missing"])
    assert code == 1
    assert isinstance(exc, YouGileError)


# --------------------------------------------------------------------------- create


def test_create_webhook(run: Any, api: Any) -> None:
    route = api.post("/api-v2/webhooks").respond(201, json={"id": HOOK_ID})
    code, out, _ = run(["create", "--url", "https://example.com/hook", "--event", "task-*"])
    assert code == 0
    assert json.loads(out)["id"] == HOOK_ID
    assert body_of(route) == {
        "url": "https://example.com/hook",
        "event": "task-*",
        "filters": [],
    }


def test_create_webhook_with_filters(run: Any, api: Any, paged: Any) -> None:
    api.get("/api-v2/projects").respond(json=paged([{"id": PROJECT_ID, "title": "Ремонт"}]))
    route = api.post("/api-v2/webhooks").respond(201, json={"id": HOOK_ID})
    code, _, _ = run(
        [
            "create",
            "--url",
            "https://example.com/hook",
            "--event",
            "task-created",
            "--filter",
            "location=Ремонт",
            "--filter",
            "title=^!",
        ]
    )
    assert code == 0
    filters = body_of(route)["filters"]
    assert {"name": "location", "value": [PROJECT_ID]} in filters
    assert {"name": "title", "value": "^!"} in filters


def test_repeated_regexp_filter_is_rejected(run: Any, api: Any) -> None:
    """title/chat_message take one regexp; an array there matches nothing."""
    route = api.post("/api-v2/webhooks").respond(201, json={"id": HOOK_ID})
    code, _, _ = run(
        [
            "create",
            "--url",
            "https://e.com/h",
            "--event",
            "task-created",
            "--filter",
            "title=^a",
            "--filter",
            "title=^b",
        ]
    )
    assert code == 2
    assert not route.called


def test_create_webhook_bad_filter(run: Any, api: Any) -> None:
    api.post("/api-v2/webhooks").respond(201, json={"id": HOOK_ID})
    code, _, _ = run(
        ["create", "--url", "https://e.com/h", "--event", "task-created", "--filter", "nope=1"]
    )
    assert code == 2


# --------------------------------------------------------------------------- edit


def test_edit_webhook_disable_resolves_name(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK, OTHER])
    route = api.put(f"/api-v2/webhooks/{OTHER_ID}").respond(json={"id": OTHER_ID})
    code, out, _ = run(["edit", "second", "--disable"])
    assert code == 0
    assert json.loads(out)["id"] == OTHER_ID
    assert body_of(route) == {"disabled": True}


def test_edit_webhook_enable_and_url(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK])
    route = api.put(f"/api-v2/webhooks/{HOOK_ID}").respond(json={"id": HOOK_ID})
    code, _, _ = run(["edit", HOOK_ID, "--enable", "--url", "https://example.com/new"])
    assert code == 0
    assert body_of(route) == {"disabled": False, "url": "https://example.com/new"}


def test_edit_webhook_undelete(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK])
    route = api.put(f"/api-v2/webhooks/{HOOK_ID}").respond(json={"id": HOOK_ID})
    code, _, _ = run(["edit", HOOK_ID, "--undelete"])
    assert code == 0
    assert body_of(route) == {"deleted": False}


def test_edit_webhook_without_changes(run: Any, api: Any) -> None:
    code, _, _ = run(["edit", HOOK_ID])
    assert code == 2


# --------------------------------------------------------------------------- delete


def test_delete_webhook_is_put_with_deleted_true(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK])
    route = api.put(f"/api-v2/webhooks/{HOOK_ID}").respond(json={"id": HOOK_ID})
    code, out, _ = run(["delete", HOOK_ID, "--yes"])
    assert code == 0
    assert json.loads(out)["id"] == HOOK_ID
    assert route.calls[0].request.method == "PUT"
    assert body_of(route) == {"deleted": True}


def test_delete_webhook_needs_yes_without_tty(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK])
    code, _, exc = run(["delete", HOOK_ID])
    assert code == 2
    assert isinstance(exc, YouGileError)


# --------------------------------------------------------------------------- events


def test_events_lists_known_strings(run: Any) -> None:
    code, out, _ = run(["events"])
    assert code == 0
    events = [row["event"] for row in json.loads(out)]
    assert "task-created" in events
    assert "user-added" in events
    assert "task-*" in events
    assert ".*" in events


def test_events_table_and_note(run: Any, capsys: Any) -> None:
    """The rich consoles are bound before CliRunner swaps the streams, so read them here."""
    code, _, _ = run(["events"], fmt="table")
    assert code == 0
    captured = capsys.readouterr()
    assert "EVENT" in captured.out
    assert "task-created" in captured.out
    assert EVENTS_NOTE in captured.err
    assert "«*»" in captured.err


# ------------------------------------------------------- defect 1: url argument


def test_create_webhook_positional_url(run: Any, api: Any) -> None:
    route = api.post("/api-v2/webhooks").respond(201, json={"id": HOOK_ID})
    code, _, _ = run(["create", "https://example.com/hook", "--event", "task-*"])
    assert code == 0
    assert body_of(route) == {
        "url": "https://example.com/hook",
        "event": "task-*",
        "filters": [],
    }


def test_create_webhook_conflicting_urls_is_usage_error(run: Any, api: Any) -> None:
    route = api.post("/api-v2/webhooks").respond(201, json={"id": HOOK_ID})
    code, _, _ = run(
        ["create", "https://a.example/hook", "--url", "https://b.example/hook", "-e", "task-*"]
    )
    assert code == 2
    assert not route.called


def test_create_webhook_without_url_is_usage_error(run: Any, api: Any) -> None:
    route = api.post("/api-v2/webhooks").respond(201, json={"id": HOOK_ID})
    code, _, _ = run(["create", "--event", "task-*"])
    assert code == 2
    assert not route.called


def test_webhook_metavars_are_russian(run: Any) -> None:
    for args, expected in (
        (["create", "--help"], "СОБЫТИЕ"),
        (["view", "--help"], "ВЕБХУК"),
        (["list", "--help"], "ЧИСЛО"),
    ):
        _, out, _ = run(args)
        assert expected in out
        assert "TEXT" not in out
        assert "INTEGER" not in out


# ------------------------------------------------------- defect 3: gendered wording


def test_missing_webhook_says_ne_najden(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK])
    _, _, exc = run(["view", "missing"])
    assert str(exc) == "Вебхук «missing» не найден."


def test_ambiguous_webhook_says_najdeno_neskolko(run: Any, api: Any) -> None:
    api.get("/api-v2/webhooks").respond(json=[HOOK, OTHER])
    _, _, exc = run(["view", "webhook.site"])
    assert "Найдено несколько (2) вебхуков с именем «webhook.site»." in str(exc)


# ------------------------------------------------------- defect 4: server 400 is exit 1


def test_server_400_on_create_is_runtime_error(run: Any, api: Any) -> None:
    api.post("/api-v2/webhooks").respond(400, json={"message": "Нельзя добавить вебхук"})
    code, _, exc = run(["create", "https://example.com/hook", "-e", "task-*"])
    assert code == 1
    assert "Нельзя добавить вебхук" in str(exc)
