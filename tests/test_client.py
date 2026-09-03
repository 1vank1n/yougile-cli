from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from yougile_cli.client import MAX_PAGE_LIMIT, RateLimiter, YouGileClient, merged_envelope
from yougile_cli.errors import (
    EXIT_AUTH,
    EXIT_ERROR,
    ApiError,
    AuthError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
    exit_code_for,
)

BASE_URL = "https://yougile.com"


def test_base_url_and_host_are_derived() -> None:
    with YouGileClient(api_key="k") as c:
        assert (c.base_url, c.host) == (BASE_URL, "yougile.com")
    with YouGileClient(api_key="k", host="my.server") as c:
        assert (c.base_url, c.host) == ("https://my.server", "my.server")
    with YouGileClient(api_key="k", base_url="https://my.server/") as c:
        assert (c.base_url, c.host) == ("https://my.server", "my.server")


def test_bearer_header_is_sent(api: respx.MockRouter, client: YouGileClient) -> None:
    route = api.get("/api-v2/users/me").respond(json={"id": "u1"})
    assert client.get("/api-v2/users/me") == {"id": "u1"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-key"


def test_auth_endpoints_go_out_without_bearer(api: respx.MockRouter, client: YouGileClient) -> None:
    route = api.post("/api-v2/auth/keys").respond(201, json={"key": "new"})
    client.post("/api-v2/auth/keys", {"login": "a", "password": "b"}, auth=False)
    assert "authorization" not in route.calls.last.request.headers


def test_extra_headers_per_request(api: respx.MockRouter, client: YouGileClient) -> None:
    route = api.get("/api-v2/projects").respond(json={"content": [], "paging": {}})
    client.get("/api-v2/projects", headers={"X-Trace": "42"})
    assert route.calls.last.request.headers["X-Trace"] == "42"


def test_none_params_and_body_fields_are_dropped(
    api: respx.MockRouter, client: YouGileClient
) -> None:
    route = api.put("/api-v2/tasks/t1").respond(json={"id": "t1"})
    client.put("/api-v2/tasks/t1", {"title": "x", "description": None}, params={"a": None})
    request = route.calls.last.request
    assert request.url.query == b""
    assert request.read() == b'{"title":"x"}'


def test_request_raw_returns_response(api: respx.MockRouter, client: YouGileClient) -> None:
    api.get("/api-v2/users/me").respond(json={"id": "u1"}, headers={"X-Rate": "50"})
    response = client.request_raw("GET", "/api-v2/users/me")
    assert isinstance(response, httpx.Response)
    assert response.status_code == 200
    assert response.headers["X-Rate"] == "50"


def test_request_raw_check_false_keeps_error_response(
    api: respx.MockRouter, client: YouGileClient
) -> None:
    api.get("/api-v2/nope").respond(404, json={"message": "no"})
    response = client.request_raw("GET", "/api-v2/nope", check=False)
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AuthError),
        (403, AuthError),
        (404, NotFoundError),
        (400, BadRequestError),
        (422, BadRequestError),
        (409, ApiError),
    ],
)
def test_status_codes_map_to_errors(
    api: respx.MockRouter, client: YouGileClient, status: int, expected: type[Exception]
) -> None:
    api.get("/api-v2/boom").respond(status, json={"message": "нельзя"})
    with pytest.raises(expected) as excinfo:
        client.get("/api-v2/boom")
    assert "нельзя" in str(excinfo.value)


def test_auth_error_exit_code_is_four(api: respx.MockRouter, client: YouGileClient) -> None:
    api.get("/api-v2/boom").respond(401, json={})
    with pytest.raises(AuthError) as excinfo:
        client.get("/api-v2/boom")
    assert excinfo.value.exit_code == 4


def test_server_error_is_retried_then_succeeds(
    api: respx.MockRouter, client: YouGileClient
) -> None:
    route = api.get("/api-v2/projects").mock(
        side_effect=[
            httpx.Response(500, json={"message": "oops"}),
            httpx.Response(200, json={"content": [], "paging": {}}),
        ]
    )
    assert client.get("/api-v2/projects") == {"content": [], "paging": {}}
    assert route.call_count == 2


def test_rate_limit_retries_and_honours_retry_after(
    api: respx.MockRouter, client: YouGileClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []
    monkeypatch.setattr("yougile_cli.client.time.sleep", slept.append)
    route = api.get("/api-v2/projects").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}, json={}),
            httpx.Response(200, json={"content": [], "paging": {}}),
        ]
    )
    client.get("/api-v2/projects")
    assert route.call_count == 2
    assert 7.0 in slept


def test_rate_limit_gives_up_and_reports_retry_after(api: respx.MockRouter) -> None:
    with YouGileClient(api_key="k", base_url=BASE_URL, max_retries=0) as client:
        api.get("/api-v2/projects").respond(429, headers={"Retry-After": "3"}, json={})
        with pytest.raises(RateLimitError) as excinfo:
            client.get("/api-v2/projects")
    assert excinfo.value.retry_after == 3.0
    assert "3 с" in str(excinfo.value)


def test_network_error_is_retried_then_raises(api: respx.MockRouter) -> None:
    with YouGileClient(api_key="k", base_url=BASE_URL, max_retries=2, backoff_factor=0.0) as client:
        route = api.get("/api-v2/projects").mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(ApiError) as excinfo:
            client.get("/api-v2/projects")
    assert route.call_count == 3
    assert "Сетевая ошибка" in str(excinfo.value)


def test_paginate_follows_next(api: respx.MockRouter, client: YouGileClient, paged: Any) -> None:
    route = api.get("/api-v2/task-list").mock(
        side_effect=[
            httpx.Response(200, json=paged([{"id": "1"}, {"id": "2"}], next_page=True)),
            httpx.Response(200, json=paged([{"id": "3"}], offset=2)),
        ]
    )
    assert [t["id"] for t in client.collect("/api-v2/task-list")] == ["1", "2", "3"]
    assert route.calls[0].request.url.params["limit"] == str(MAX_PAGE_LIMIT)
    assert route.calls[1].request.url.params["offset"] == "2"


def test_paginate_stops_at_max_items(
    api: respx.MockRouter, client: YouGileClient, paged: Any
) -> None:
    api.get("/api-v2/task-list").respond(json=paged([{"id": "1"}, {"id": "2"}], next_page=True))
    assert len(client.collect("/api-v2/task-list", max_items=2)) == 2


def test_paginate_handles_bare_list(api: respx.MockRouter, client: YouGileClient) -> None:
    api.get("/api-v2/auth/keys/get").respond(json=[{"key": "a"}, {"key": "b"}])
    assert len(client.collect("/api-v2/auth/keys/get")) == 2


def test_paginate_empty_content(api: respx.MockRouter, client: YouGileClient, paged: Any) -> None:
    api.get("/api-v2/projects").respond(json=paged([]))
    assert client.collect("/api-v2/projects") == []


def test_rate_limiter_blocks_when_bucket_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    # Часы под контролем теста: иначе цикл acquire крутится 30 секунд реального времени.
    now = [1000.0]
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    monkeypatch.setattr("yougile_cli.client.time.monotonic", lambda: now[0])
    monkeypatch.setattr("yougile_cli.client.time.sleep", fake_sleep)

    limiter = RateLimiter(rate=2, period=60.0)
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()  # третий запрос упирается в лимит
    assert slept == [30.0]


def test_upload_file_is_multipart(
    api: respx.MockRouter, client: YouGileClient, tmp_path: Path
) -> None:
    sample = tmp_path / "note.txt"
    sample.write_text("привет", encoding="utf-8")
    route = api.post("/api-v2/upload-file").respond(
        json={"result": "ok", "url": "/f/1", "fullUrl": "https://yougile.com/f/1"}
    )
    assert client.upload_file(sample)["url"] == "/f/1"
    content_type = route.calls.last.request.headers["content-type"]
    assert content_type.startswith("multipart/form-data; boundary=")


def test_no_content_response_is_none(api: respx.MockRouter, client: YouGileClient) -> None:
    api.delete("/api-v2/auth/keys/abc").respond(204)
    assert client.delete("/api-v2/auth/keys/abc") is None


def test_set_api_key_updates_header(api: respx.MockRouter, client: YouGileClient) -> None:
    route = api.get("/api-v2/users/me").respond(json={"id": "u"})
    client.set_api_key("second")
    client.get("/api-v2/users/me")
    assert route.calls.last.request.headers["Authorization"] == "Bearer second"
    client.set_api_key(None)
    client.get("/api-v2/users/me")
    assert "authorization" not in route.calls.last.request.headers


def test_bearer_never_leaves_the_authenticated_host(client: YouGileClient) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get("http://attacker.example/steal").respond(json={"ok": True})
        client.request_raw("GET", "http://attacker.example/steal")
    assert "authorization" not in route.calls.last.request.headers


def test_bearer_survives_a_hostname_with_a_port() -> None:
    """`host:port` не совпадает с `httpx.URL.host`, и ключ раньше отваливался (дефект №3)."""
    ported = YouGileClient(api_key="secret", host="yg.corp.local:8443")
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://yg.corp.local:8443/api-v2/projects").respond(json={"id": "p"})
        ported.request_raw("GET", "/api-v2/projects")
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret"


def test_bearer_covers_the_web_host_of_the_cloud(client: YouGileClient) -> None:
    """`ru.yougile.com` — веб-лицо того же облака, что и API на `yougile.com`."""
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://ru.yougile.com/user-data/a/b.png").respond(content=b"1234")
        with client.stream("GET", "https://ru.yougile.com/user-data/a/b.png") as response:
            response.read()
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-key"


def test_retry_after_negative_is_not_slept(
    api: respx.MockRouter, client: YouGileClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []
    monkeypatch.setattr("yougile_cli.client.time.sleep", slept.append)
    api.get("/api-v2/projects").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "-1"}, json={}),
            httpx.Response(200, json={"id": "p1"}),
        ]
    )
    assert client.get("/api-v2/projects") == {"id": "p1"}
    assert slept == [0.0]


def test_retry_after_http_date_is_parsed() -> None:
    from yougile_cli.client import _retry_after_seconds

    response = httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert _retry_after_seconds(response) == 0.0


def test_huge_retry_after_is_reported_not_slept(
    api: respx.MockRouter, client: YouGileClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    slept: list[float] = []
    monkeypatch.setattr("yougile_cli.client.time.sleep", slept.append)
    api.get("/api-v2/projects").respond(429, headers={"Retry-After": "3600"}, json={})
    with pytest.raises(RateLimitError) as excinfo:
        client.get("/api-v2/projects")
    assert excinfo.value.retry_after == 3600.0
    assert slept == []


def test_post_is_not_retried_after_a_server_error(
    api: respx.MockRouter, client: YouGileClient
) -> None:
    """A write the server may already have applied must never be replayed."""
    route = api.post("/api-v2/tasks").mock(
        side_effect=[
            httpx.Response(502, json={"message": "bad gateway"}),
            httpx.Response(201, json={"id": "t1"}),
        ]
    )
    with pytest.raises(ApiError):
        client.post("/api-v2/tasks", {"title": "X"})
    assert route.call_count == 1


def test_post_is_not_retried_after_a_network_error(api: respx.MockRouter) -> None:
    with YouGileClient(api_key="k", base_url=BASE_URL, max_retries=2, backoff_factor=0.0) as client:
        route = api.post("/api-v2/tasks").mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(ApiError):
            client.post("/api-v2/tasks", {"title": "X"})
    assert route.call_count == 1


def test_post_is_still_retried_after_a_rate_limit(
    api: respx.MockRouter, client: YouGileClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """429 means the request was rejected outright, so no write happened."""
    monkeypatch.setattr("yougile_cli.client.time.sleep", lambda _s: None)
    route = api.post("/api-v2/tasks").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}, json={}),
            httpx.Response(201, json={"id": "t1"}),
        ]
    )
    assert client.post("/api-v2/tasks", {"title": "X"}) == {"id": "t1"}
    assert route.call_count == 2


# ------------------------------------------------------- server errors are not usage errors


@pytest.mark.parametrize("status", [400, 404, 409, 422, 429, 500])
def test_server_rejection_exits_with_one(
    api: respx.MockRouter, client: YouGileClient, status: int
) -> None:
    """gh reserves exit 2 for bad arguments; «нельзя удалить последнюю доску» is not that."""
    api.delete("/api-v2/boards/b1").respond(status, json={"message": "нельзя"})
    with pytest.raises(ApiError) as excinfo:
        client.delete("/api-v2/boards/b1")
    assert exit_code_for(excinfo.value) == EXIT_ERROR


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_still_exits_with_four(
    api: respx.MockRouter, client: YouGileClient, status: int
) -> None:
    api.get("/api-v2/boards").respond(status, json={"message": "нет доступа"})
    with pytest.raises(AuthError) as excinfo:
        client.get("/api-v2/boards")
    assert exit_code_for(excinfo.value) == EXIT_AUTH


# ------------------------------------------------------------------------------- paging


def test_merged_envelope_describes_the_merged_result() -> None:
    """After --paginate the paging block must describe the glued list, not the last page."""
    merged = merged_envelope(
        list(range(1437)),
        {"paging": {"count": 1437, "limit": 1000, "offset": 1000, "next": False}, "extra": 1},
    )
    assert merged["paging"] == {"count": 1437, "limit": 1437, "offset": 0, "next": False}
    assert len(merged["content"]) == 1437
    assert merged["extra"] == 1


def test_merged_envelope_without_envelope() -> None:
    assert merged_envelope([]) == {
        "content": [],
        "paging": {"count": 0, "limit": 0, "offset": 0, "next": False},
    }


# ----------------------------------------------------------------------------- streaming


def test_stream_yields_chunks_with_bearer(api: respx.MockRouter, client: YouGileClient) -> None:
    route = api.get("/user-data/a/b.png").respond(200, content=b"0123456789")
    with client.stream("GET", "/user-data/a/b.png") as response:
        assert b"".join(response.iter_bytes(4)) == b"0123456789"
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-key"


def test_stream_raises_on_error_status(api: respx.MockRouter, client: YouGileClient) -> None:
    api.get("/user-data/missing").respond(404, json={"message": "нет файла"})
    with pytest.raises(NotFoundError), client.stream("GET", "/user-data/missing"):
        pass  # pragma: no cover - the context manager never opens
