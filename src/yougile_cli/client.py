"""Synchronous HTTP client for the YouGile REST API v2.

Facts baked in here:

* base URL is a host root — every path already carries the ``/api-v2`` prefix;
* ``Authorization: Bearer <key>`` on everything except ``POST /api-v2/auth/*``
  (pass ``auth=False`` there);
* list endpoints answer ``{"paging": {...}, "content": [...]}`` with ``limit``
  capped at 1000;
* the company-wide budget is 50 requests per minute, so a token bucket paces
  outgoing calls and 429/5xx are retried, honouring ``Retry-After``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from . import __version__
from .errors import (
    ApiError,
    AuthError,
    BadRequestError,
    NotFoundError,
    RateLimitError,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_RATE_LIMIT",
    "MAX_PAGE_LIMIT",
    "RateLimiter",
    "YouGileClient",
    "merged_envelope",
]

DEFAULT_BASE_URL = "https://yougile.com"
DEFAULT_HOST = "yougile.com"
# The cloud serves its web links from ru.yougile.com while the API answers on
# yougile.com: for the bearer header the two are the same origin.
WEB_HOST = "ru.yougile.com"
_CLOUD_HOSTS = frozenset({DEFAULT_HOST, WEB_HOST})
DEFAULT_RATE_LIMIT = 50
RATE_PERIOD = 60.0
MAX_PAGE_LIMIT = 1000
# Upper bound for a server-requested pause: longer waits are reported, not slept through.
MAX_RETRY_AFTER = 60.0
# Only these may be replayed after a 5xx or a broken connection.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE", "PUT", "DELETE"})


class RateLimiter:
    """Token bucket: `rate` requests per `period` seconds, shared between threads."""

    def __init__(self, rate: int = DEFAULT_RATE_LIMIT, period: float = RATE_PERIOD) -> None:
        self.rate = max(1, int(rate))
        self.period = float(period)
        self._tokens = float(self.rate)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self, now: float) -> None:
        elapsed = now - self._updated
        if elapsed <= 0:
            return
        self._tokens = min(float(self.rate), self._tokens + elapsed * self.rate / self.period)
        self._updated = now

    def acquire(self, tokens: float = 1.0) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._refill(now)
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                deficit = tokens - self._tokens
                wait = deficit * self.period / self.rate
            time.sleep(max(wait, 0.01))


def _strip_none_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return None
    cleaned = {k: v for k, v in params.items() if v is not None}
    return cleaned or None


def _strip_none_json(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {k: v for k, v in payload.items() if v is not None}
    return payload


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """RFC 7231 allows both a delay in seconds and an HTTP-date; never return a negative wait."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    text = raw.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (moment - datetime.now(UTC)).total_seconds())


def _host_of(base_url: str) -> str:
    return httpx.URL(base_url).host or DEFAULT_HOST


def merged_envelope(
    content: list[Any],
    envelope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild a ``{paging, content}`` body after pages were glued together.

    The paging block of the last page describes that page, not the merged
    result, so `--paginate` output would otherwise claim a limit of 1000 next to
    1437 items. Everything the endpoint returned besides paging is kept.
    """
    merged = list(content)
    result: dict[str, Any] = {k: v for k, v in (envelope or {}).items() if k != "content"}
    result["content"] = merged
    result["paging"] = {
        "count": len(merged),
        "limit": len(merged),
        "offset": 0,
        "next": False,
    }
    return result


class YouGileClient:
    """Thin synchronous wrapper over the YouGile REST API v2."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        host: str | None = None,
        timeout: float = 30.0,
        rate_limit: int = DEFAULT_RATE_LIMIT,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        backoff_factor: float = 0.5,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if base_url:
            resolved_base = base_url.rstrip("/")
        elif host:
            resolved_base = f"https://{host.strip().rstrip('/')}"
        else:
            resolved_base = DEFAULT_BASE_URL
        self.api_key = api_key
        self.base_url = resolved_base or DEFAULT_BASE_URL
        self.host = (host or "").strip() or _host_of(self.base_url)
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff_factor = backoff_factor
        self.limiter = RateLimiter(rate_limit)
        base_headers = self._base_headers()
        if headers:
            base_headers.update(headers)
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers=base_headers,
        )

    def _is_own_host(self, url: httpx.URL) -> bool:
        """The bearer token stays on the authenticated host, the way `gh api` does it.

        ``self.host`` may carry a port (``yg.corp.local:8443``) while ``httpx.URL.host``
        never does, and the public cloud serves its web links from ``ru.yougile.com``
        while the API answers on ``yougile.com`` — one origin as far as auth goes.
        """
        host = (url.host or "").lower()
        if not host:
            return True
        base = httpx.URL(self.base_url)
        own = (base.host or "").lower()
        if url.port != base.port:
            return False
        if host == own:
            return True
        return {host, own} <= _CLOUD_HOSTS

    def _base_headers(self) -> dict[str, str]:
        # Content-Type is set per request: httpx must be free to build its own
        # multipart boundary for /api-v2/upload-file.
        headers = {
            "Accept": "application/json",
            "User-Agent": f"yougile-cli/{__version__}",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def set_api_key(self, api_key: str | None) -> None:
        self.api_key = api_key
        if api_key:
            self._http.headers["Authorization"] = f"Bearer {api_key}"
        else:
            self._http.headers.pop("Authorization", None)

    # ------------------------------------------------------------------ requests

    def request_raw(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        files: Any = None,
        content: bytes | str | None = None,
        headers: Mapping[str, str] | None = None,
        auth: bool = True,
        check: bool = True,
    ) -> httpx.Response:
        """Send one request and return the raw response (`yougile api --include`)."""
        clean_params = _strip_none_params(params)
        clean_json = _strip_none_json(json) if json is not None else None
        # A POST the server may already have applied must not be replayed: a 5xx or a
        # dropped connection says nothing about whether the write landed.
        idempotent = method.upper() in IDEMPOTENT_METHODS

        request_headers: dict[str, str] = {}
        if clean_json is not None and files is None:
            request_headers["Content-Type"] = "application/json"
        if content is not None and files is None:
            request_headers.setdefault("Content-Type", "application/json")
        if headers:
            request_headers.update(headers)

        attempt = 0
        while True:
            self.limiter.acquire()
            request = self._http.build_request(
                method.upper(),
                path,
                json=clean_json,
                params=clean_params,
                files=files,
                content=content,
                headers=request_headers or None,
            )
            if not auth or not self._is_own_host(request.url):
                # POST /api-v2/auth/* must go out without a bearer token, and the key
                # must never leak to a foreign host (`yougile api https://...`).
                request.headers.pop("Authorization", None)
            try:
                response = self._http.send(request)
            except httpx.HTTPError as exc:
                if idempotent and attempt < self.max_retries:
                    time.sleep(self._backoff(attempt))
                    attempt += 1
                    continue
                raise ApiError(
                    f"Сетевая ошибка: {exc}",
                    method=method.upper(),
                    url=str(path),
                    hint="Проверьте соединение и адрес хоста.",
                ) from exc

            if response.status_code < 400:
                return response

            # 429 means the request was rejected outright, so replaying it is safe
            # for any verb; a 5xx may have been applied already.
            retryable = response.status_code == 429 or (idempotent and response.status_code >= 500)
            if retryable and attempt < self.max_retries:
                delay = _retry_after_seconds(response)
                if delay is not None and delay > MAX_RETRY_AFTER:
                    # Blocking the CLI for the server's whole cooldown is worse than
                    # reporting it: the error carries retry_after for the caller.
                    if not check:
                        return response
                    self._raise_for_status(method, path, response)
                time.sleep(delay if delay is not None else self._backoff(attempt))
                attempt += 1
                continue
            if not check:
                return response
            self._raise_for_status(method, path, response)

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        files: Any = None,
        content: bytes | str | None = None,
        headers: Mapping[str, str] | None = None,
        auth: bool = True,
    ) -> Any:
        """Send one request and return the decoded JSON body."""
        response = self.request_raw(
            method,
            path,
            json=json,
            params=params,
            files=files,
            content=content,
            headers=headers,
            auth=auth,
        )
        return self._parse(response)

    def _backoff(self, attempt: int) -> float:
        return self.backoff_factor * (2**attempt)

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def _raise_for_status(self, method: str, path: str, response: httpx.Response) -> None:
        payload = self._parse(response)
        status = response.status_code
        kwargs: dict[str, Any] = {
            "status_code": status,
            "method": method.upper(),
            "url": str(response.request.url) if response.request else path,
            "payload": payload,
        }
        if status in (401, 403):
            raise AuthError("Доступ запрещён, проверьте API-ключ и права", **kwargs)
        if status == 404:
            raise NotFoundError("Объект не найден", **kwargs)
        if status == 429:
            raise RateLimitError(
                "Превышен лимит запросов (50 в минуту)",
                retry_after=_retry_after_seconds(response),
                **kwargs,
            )
        if status in (400, 422):
            # A rejection by the server is a runtime failure (exit 1); exit 2 belongs
            # to validation we do ourselves before the request goes out.
            raise BadRequestError("Некорректный запрос", **kwargs)
        if status < 500:
            raise ApiError("Запрос отклонён сервером", **kwargs)
        raise ApiError("Внутренняя ошибка сервера YouGile", **kwargs)

    # ------------------------------------------------------------------ verbs

    def get(self, path: str, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request("GET", path, params=params, **kwargs)

    def post(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return self.request("POST", path, json=json, **kwargs)

    def put(self, path: str, json: Any = None, **kwargs: Any) -> Any:
        return self.request("PUT", path, json=json, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    # ------------------------------------------------------------------ paging

    def paginate(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        limit: int = MAX_PAGE_LIMIT,
        max_items: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Walk a {paging, content} list endpoint page by page."""
        page_size = max(1, min(int(limit), MAX_PAGE_LIMIT))
        if max_items:
            page_size = max(1, min(page_size, int(max_items)))
        offset = 0
        yielded = 0
        while True:
            query = dict(params or {})
            query["limit"] = page_size
            query["offset"] = offset
            data = self.get(path, params=query)
            if isinstance(data, list):
                content: list[Any] = data
                paging: dict[str, Any] = {}
            elif isinstance(data, dict):
                content = data.get("content") or []
                paging = data.get("paging") or {}
            else:
                return
            if not content:
                return
            for item in content:
                yield item
                yielded += 1
                if max_items and yielded >= max_items:
                    return
            if not paging.get("next"):
                return
            offset += len(content)

    def collect(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        max_items: int | None = None,
    ) -> list[dict[str, Any]]:
        """Whole list endpoint as a list; ``max_items=0`` or ``None`` means all."""
        return list(self.paginate(path, params, max_items=max_items))

    def stream(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        auth: bool = True,
    ) -> AbstractContextManager[httpx.Response]:
        """Open a streaming response (downloads); the body is never buffered whole."""
        return self._stream(method, path, params=params, headers=headers, auth=auth)

    @contextmanager
    def _stream(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        auth: bool = True,
    ) -> Iterator[httpx.Response]:
        self.limiter.acquire()
        request = self._http.build_request(
            method.upper(),
            path,
            params=_strip_none_params(params),
            headers=dict(headers) if headers else None,
        )
        if not auth or not self._is_own_host(request.url):
            request.headers.pop("Authorization", None)
        try:
            # /user-data/... отвечает 302 на user-data.<хост>, и это хранилище отклоняет
            # Authorization с ошибкой 400 — httpx снимает заголовок сам при смене origin.
            response = self._http.send(request, stream=True, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise ApiError(
                f"Сетевая ошибка: {exc}",
                method=method.upper(),
                url=str(path),
                hint="Проверьте соединение и адрес хоста.",
            ) from exc
        try:
            if response.status_code >= 400:
                response.read()
                self._raise_for_status(method, path, response)
            if response.status_code >= 300:
                response.read()
                raise ApiError(
                    f"Сервер ответил перенаправлением {response.status_code} без адреса.",
                    method=method.upper(),
                    url=str(path),
                    status_code=response.status_code,
                )
            yield response
        finally:
            response.close()

    def upload_file(self, path: Path | str) -> dict[str, Any]:
        """POST /api-v2/upload-file as multipart/form-data."""
        file_path = Path(path)
        with file_path.open("rb") as handle:
            result = self.request(
                "POST",
                "/api-v2/upload-file",
                files={"file": (file_path.name, handle)},
            )
        return result if isinstance(result, dict) else {"result": result}

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> YouGileClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
