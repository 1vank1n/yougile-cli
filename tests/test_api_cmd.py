"""Tests for `yougile api` — the gh-style escape hatch."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
import respx
import typer
from typer.testing import CliRunner

from yougile_cli.commands.api_cmd import api_cmd, normalize_endpoint
from yougile_cli.config import ResolvedAuth
from yougile_cli.context import AppContext
from yougile_cli.errors import NotFoundError, ValidationError, exit_code_for
from yougile_cli.output import OutputFormat, OutputOptions

from .conftest import BASE_URL, HOST, TEST_KEY

COMPANY_ID = "22222222-2222-4222-8222-222222222222"


def _auth(api_key: str | None = TEST_KEY) -> ResolvedAuth:
    return ResolvedAuth(
        host=HOST,
        base_url=BASE_URL,
        api_key=api_key,
        company_id=COMPANY_ID,
        source="flag",
    )


@pytest.fixture
def invoke(runner: CliRunner) -> Callable[..., Any]:
    """Run `api_cmd` inside a throwaway Typer app carrying a real AppContext."""

    def _invoke(
        args: list[str],
        *,
        out: OutputOptions | None = None,
        auth: ResolvedAuth | None = None,
        input: str | None = None,
    ) -> Any:
        application = typer.Typer()

        @application.callback()
        def _main(ctx: typer.Context) -> None:
            ctx.obj = AppContext(auth=auth or _auth(), out=out or OutputOptions())

        application.command("api")(api_cmd)
        return runner.invoke(application, ["api", *args], input=input)

    return _invoke


# --------------------------------------------------------------------- endpoint


@pytest.mark.parametrize(
    "given",
    ["task-list", "/task-list", "/api-v2/task-list"],
)
def test_normalize_endpoint_variants(given: str) -> None:
    assert normalize_endpoint(given) == "/api-v2/task-list"


def test_normalize_endpoint_keeps_absolute_url() -> None:
    url = "https://example.com/api-v2/task-list"
    assert normalize_endpoint(url) == url


def test_normalize_endpoint_substitutes_company() -> None:
    assert normalize_endpoint("companies/{company}", company_id=COMPANY_ID) == (
        f"/api-v2/companies/{COMPANY_ID}"
    )


def test_normalize_endpoint_without_company_fails() -> None:
    with pytest.raises(ValidationError):
        normalize_endpoint("companies/{company}")


def test_normalize_endpoint_empty_fails() -> None:
    with pytest.raises(ValidationError):
        normalize_endpoint("   ")


# ------------------------------------------------------------------ happy paths


def test_get_is_the_default_method(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    route = api.get("/api-v2/task-list").respond(json=paged([{"id": "t1", "title": "Задача"}]))
    result = invoke(["task-list"])
    assert result.exit_code == 0, result.output
    assert route.called
    assert route.calls.last.request.method == "GET"
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TEST_KEY}"
    assert json.loads(result.stdout)["content"][0]["title"] == "Задача"


def test_short_endpoint_hits_the_api_v2_prefix(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    route = api.get("/api-v2/users/me").respond(json={"id": "u1"})
    assert invoke(["/users/me"]).exit_code == 0
    assert route.called


def test_query_string_in_the_endpoint_is_kept(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    route = api.get("/api-v2/task-list").respond(json=paged([]))
    assert invoke(["task-list?columnId=c1&limit=5"]).exit_code == 0
    request = route.calls.last.request
    assert request.url.params["columnId"] == "c1"
    assert request.url.params["limit"] == "5"


def test_raw_fields_turn_the_call_into_a_post(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    route = api.post("/api-v2/tasks").respond(201, json={"id": "t1"})
    result = invoke(["tasks", "-f", "title=Купить хлеб", "-f", "columnId=c1"])
    assert result.exit_code == 0, result.output
    request = route.calls.last.request
    assert request.method == "POST"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == {"title": "Купить хлеб", "columnId": "c1"}
    assert json.loads(result.stdout) == {"id": "t1"}


def test_typed_fields_keep_their_types(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.post("/api-v2/tasks").respond(201, json={"id": "t1"})
    result = invoke(
        [
            "tasks",
            "-f",
            "title=Задача",
            "-F",
            "completed=true",
            "-F",
            "timer=42",
            "-F",
            "deadline=null",
        ]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content) == {
        "title": "Задача",
        "completed": True,
        "timer": 42,
        "deadline": None,
    }


def test_fields_become_query_params_for_an_explicit_get(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    route = api.get("/api-v2/task-list").respond(json=paged([]))
    assert invoke(["task-list", "-X", "GET", "-f", "columnId=c1", "-F", "limit=7"]).exit_code == 0
    request = route.calls.last.request
    assert request.url.params["columnId"] == "c1"
    assert request.url.params["limit"] == "7"
    assert not request.content


def test_delete_is_a_put_with_deleted_true(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    """There is no DELETE for tasks: removal is PUT {"deleted": true}."""
    route = api.put("/api-v2/tasks/t1").respond(json={"id": "t1"})
    result = invoke(["tasks/t1", "-X", "PUT", "-F", "deleted=true"])
    assert result.exit_code == 0, result.output
    assert route.calls.last.request.method == "PUT"
    assert json.loads(route.calls.last.request.content) == {"deleted": True}


def test_input_file_is_sent_verbatim(
    invoke: Callable[..., Any], api: respx.MockRouter, tmp_path: Any
) -> None:
    body = tmp_path / "body.json"
    body.write_text('{"title": "Из файла"}', encoding="utf-8")
    route = api.post("/api-v2/tasks").respond(201, json={"id": "t1"})
    assert invoke(["tasks", "--input", str(body)]).exit_code == 0
    assert json.loads(route.calls.last.request.content) == {"title": "Из файла"}


def test_input_dash_reads_stdin(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.post("/api-v2/tasks").respond(201, json={"id": "t1"})
    result = invoke(["tasks", "--input", "-"], input='{"title": "Из stdin"}')
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls.last.request.content) == {"title": "Из stdin"}


def test_custom_headers_are_sent(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    route = api.get("/api-v2/users/me").respond(json={"id": "u1"})
    assert invoke(["users/me", "-H", "X-Trace: abc"]).exit_code == 0
    assert route.calls.last.request.headers["X-Trace"] == "abc"


def test_auth_endpoints_go_out_without_a_bearer(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    """POST /api-v2/auth/* takes no Authorization header."""
    route = api.post("/api-v2/auth/companies").respond(json={"content": []})
    result = invoke(
        ["auth/companies", "-f", "login=ivan@example.com", "-f", "password=secret"],
        auth=_auth(api_key=None),
    )
    assert result.exit_code == 0, result.output
    assert "Authorization" not in route.calls.last.request.headers


# ---------------------------------------------------------------------- paginate


def test_paginate_glues_content_pages(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    route = api.get("/api-v2/task-list").mock(
        side_effect=[
            respx.MockResponse(json=paged([{"id": "t1"}, {"id": "t2"}], next_page=True)),
            respx.MockResponse(json=paged([{"id": "t3"}], offset=2)),
        ]
    )
    result = invoke(["task-list", "--paginate"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [item["id"] for item in payload["content"]] == ["t1", "t2", "t3"]
    assert payload["paging"] == {"count": 3, "limit": 3, "offset": 0, "next": False}
    assert len(route.calls) == 2
    assert route.calls[1].request.url.params["offset"] == "2"


def test_paginate_stops_when_a_bare_list_endpoint_ignores_offset(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    """`webhooks` and `chat-subscribers` have no limit/offset: they repeat the same array."""
    route = api.get("/api-v2/tasks/T1/chat-subscribers").mock(
        return_value=respx.MockResponse(json=["u1", "u2"])
    )
    result = invoke(["tasks/T1/chat-subscribers?limit=2", "--paginate"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == ["u1", "u2"]
    assert len(route.calls) == 2


def test_paginate_rejects_input(invoke: Callable[..., Any], tmp_path: Any) -> None:
    body = tmp_path / "b.json"
    body.write_text("{}", encoding="utf-8")
    result = invoke(["tasks", "--paginate", "--input", str(body)])
    assert isinstance(result.exception, ValidationError)
    assert exit_code_for(result.exception) == 2


def test_paginate_rejects_non_get(invoke: Callable[..., Any]) -> None:
    result = invoke(["tasks", "--paginate", "-X", "POST"])
    assert isinstance(result.exception, ValidationError)


# ------------------------------------------------------------------- formatting


def test_include_prints_the_status_line_and_headers(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    api.get("/api-v2/users/me").respond(json={"id": "u1"}, headers={"X-Req": "42"})
    result = invoke(["users/me", "--include"])
    assert result.exit_code == 0, result.output
    assert "200" in result.stdout.splitlines()[0]
    assert "x-req: 42" in result.stdout.lower()
    assert '"id": "u1"' in result.stdout


def test_silent_prints_nothing(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    api.get("/api-v2/users/me").respond(json={"id": "u1"})
    result = invoke(["users/me", "--silent"])
    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_verbose_dumps_the_request_to_stderr(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    api.post("/api-v2/tasks").respond(201, json={"id": "t1"})
    result = invoke(["tasks", "-f", "title=X", "--verbose"])
    assert result.exit_code == 0, result.output
    assert "> POST https://yougile.com/api-v2/tasks" in result.stderr
    assert "title" in result.stderr


def test_non_json_answer_is_printed_as_text(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    api.get("/api-v2/ping").respond(200, text="pong", headers={"Content-Type": "text/plain"})
    result = invoke(["ping"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "pong"


def test_empty_body_prints_nothing(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    api.get("/api-v2/ping").respond(204)
    result = invoke(["ping"])
    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_jq_filters_the_json(
    invoke: Callable[..., Any],
    api: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    paged: Callable[..., dict[str, Any]],
) -> None:
    seen: dict[str, Any] = {}

    class _Proc:
        returncode = 0
        stdout = "t1\n"
        stderr = ""

    def _fake_run(cmd: list[str], **kwargs: Any) -> Any:
        seen["cmd"] = cmd
        seen["input"] = kwargs.get("input")
        return _Proc()

    monkeypatch.setattr("yougile_cli.output.subprocess.run", _fake_run)
    api.get("/api-v2/task-list").respond(json=paged([{"id": "t1"}]))
    result = invoke(["task-list", "-q", ".content[].id"])
    assert result.exit_code == 0, result.output
    assert seen["cmd"] == ["jq", "-r", ".content[].id"]
    assert json.loads(seen["input"])["content"] == [{"id": "t1"}]
    assert result.stdout.strip() == "t1"


def test_json_field_selection(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    api.get("/api-v2/task-list").respond(
        json=paged([{"id": "t1", "title": "Задача", "columnId": "c1"}])
    )
    result = invoke(["task-list"], out=OutputOptions(json_fields=["id", "title"]))
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"id": "t1", "title": "Задача"}]


def test_output_format_flag_still_wins(
    invoke: Callable[..., Any], api: respx.MockRouter, paged: Callable[..., dict[str, Any]]
) -> None:
    api.get("/api-v2/task-list").respond(json=paged([{"id": "t1", "title": "Задача"}]))
    result = invoke(["task-list"], out=OutputOptions(fmt=OutputFormat.IDS))
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "t1"


# ------------------------------------------------------------------ error paths


def test_not_found_exits_with_one(invoke: Callable[..., Any], api: respx.MockRouter) -> None:
    api.get("/api-v2/tasks/nope").respond(404, json={"message": "Not found"})
    result = invoke(["tasks/nope"])
    assert isinstance(result.exception, NotFoundError)
    assert exit_code_for(result.exception) == 1


def test_unknown_method_is_a_usage_error(invoke: Callable[..., Any]) -> None:
    result = invoke(["task-list", "-X", "FETCH"])
    assert isinstance(result.exception, ValidationError)
    assert exit_code_for(result.exception) == 2


def test_broken_header_is_a_usage_error(invoke: Callable[..., Any]) -> None:
    result = invoke(["task-list", "-H", "broken"])
    assert isinstance(result.exception, ValidationError)
    assert exit_code_for(result.exception) == 2


def test_input_and_fields_are_mutually_exclusive(invoke: Callable[..., Any], tmp_path: Any) -> None:
    body = tmp_path / "b.json"
    body.write_text("{}", encoding="utf-8")
    result = invoke(["tasks", "--input", str(body), "-f", "title=X"])
    assert isinstance(result.exception, ValidationError)
    assert exit_code_for(result.exception) == 2


def test_missing_input_file_is_a_usage_error(invoke: Callable[..., Any], tmp_path: Any) -> None:
    result = invoke(["tasks", "--input", str(tmp_path / "absent.json")])
    assert isinstance(result.exception, ValidationError)
    assert exit_code_for(result.exception) == 2


# ------------------------------------------- defect 6: the merged envelope describes the merge


def test_paginate_rebuilds_paging_for_the_merged_result(
    invoke: Callable[..., Any], api: respx.MockRouter
) -> None:
    """`limit` must describe the glued result, not the last page that was fetched."""
    first = {
        "paging": {"count": 2, "limit": 2, "offset": 10, "next": True},
        "content": [{"id": "t1"}, {"id": "t2"}],
        "extra": "сохраняется",
    }
    second = {
        "paging": {"count": 1, "limit": 2, "offset": 12, "next": False},
        "content": [{"id": "t3"}],
    }
    api.get("/api-v2/task-list").mock(
        side_effect=[respx.MockResponse(json=first), respx.MockResponse(json=second)]
    )
    result = invoke(["task-list?limit=2&offset=10", "--paginate"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["paging"] == {"count": 3, "limit": 3, "offset": 0, "next": False}
    assert [item["id"] for item in payload["content"]] == ["t1", "t2", "t3"]
    assert payload["extra"] == "сохраняется"


def test_api_metavars_are_russian(invoke: Callable[..., Any]) -> None:
    output = invoke(["--help"]).output
    for expected in ("ЭНДПОИНТ", "МЕТОД", "ПОЛЕ=ЗНАЧЕНИЕ", "ЗАГОЛОВОК", "ВЫРАЖЕНИЕ", "ФАЙЛ"):
        assert expected in output
    assert "TEXT" not in output
