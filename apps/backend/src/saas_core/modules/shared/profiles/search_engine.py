"""The catalogue's search engine (Meilisearch), spoken to over its REST API.

ADR-064. The engine holds a copy the database can rebuild at any time, so every
call here may fail without losing anything: a failed write is picked up by the
reconcile sweep, a failed search falls back to PostgreSQL. That is why the one
error this module raises is `SearchEngineUnavailable`, whatever went wrong.

Plain `urllib`, like the image provider: the surface is six calls and a client
library would be a dependency for the sake of a JSON body.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Protocol

from django.conf import settings

#: Index writes and settings run in the worker, where waiting is cheap; the
#: search timeout is a setting, because a visitor waits for that one.
WRITE_TIMEOUT_SECONDS = 10.0
#: Documents fetched per page by the reconcile sweep.
PAGE = 1000


class SearchEngineUnavailable(Exception):
    """The engine did not answer, answered an error, or is not configured."""


class Engine(Protocol):
    def ensure_index(self, index: str, index_settings: dict[str, Any]) -> None: ...
    def upsert(self, index: str, documents: list[dict[str, Any]]) -> None: ...
    def delete(self, index: str, ids: list[str]) -> None: ...
    def documents(self, index: str, fields: list[str]) -> list[dict[str, Any]]: ...
    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]: ...
    def rebuild(
        self, index: str, index_settings: dict[str, Any], documents: list[dict[str, Any]]
    ) -> None: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):  # type: ignore[no-untyped-def]
        return None


class Meilisearch:
    def __init__(self, url: str, api_key: str, search_timeout: float) -> None:
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.search_timeout = search_timeout
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _call(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        timeout: float = WRITE_TIMEOUT_SECONDS,
        missing_ok: bool = False,
    ) -> Any:
        request = urllib.request.Request(
            self.url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise SearchEngineUnavailable(f"search_http_{error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise SearchEngineUnavailable("search_unreachable") from error
        try:
            return json.loads(raw) if raw else None
        except ValueError as error:
            raise SearchEngineUnavailable("search_response_malformed") from error

    def _wait(self, task: Any, timeout: float = 60.0) -> None:
        """Index writes are queued tasks; a rebuild has to know they finished."""
        uid = task["taskUid"]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self._call("GET", f"/tasks/{uid}")
            if state["status"] == "succeeded":
                return
            if state["status"] in {"failed", "canceled"}:
                code = (state.get("error") or {}).get("code", "unknown")
                raise SearchEngineUnavailable(f"search_task_{code}")
            time.sleep(0.2)
        raise SearchEngineUnavailable("search_task_timeout")

    def ensure_index(self, index: str, index_settings: dict[str, Any]) -> None:
        quoted = urllib.parse.quote(index)
        if self._call("GET", f"/indexes/{quoted}", missing_ok=True) is None:
            self._wait(self._call("POST", "/indexes", {"uid": index, "primaryKey": "id"}))
        current = self._call("GET", f"/indexes/{quoted}/settings")
        if _differs(current, index_settings):
            # Queued ahead of any document written after it, so no wait here.
            self._call("PATCH", f"/indexes/{quoted}/settings", index_settings)

    def upsert(self, index: str, documents: list[dict[str, Any]]) -> None:
        if documents:
            self._call("PUT", f"/indexes/{urllib.parse.quote(index)}/documents", documents)

    def delete(self, index: str, ids: list[str]) -> None:
        if ids:
            self._call("POST", f"/indexes/{urllib.parse.quote(index)}/documents/delete-batch", ids)

    def documents(self, index: str, fields: list[str]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        query = f"fields={urllib.parse.quote(','.join(fields))}&limit={PAGE}"
        while True:
            page = self._call(
                "GET",
                f"/indexes/{urllib.parse.quote(index)}/documents?{query}&offset={len(found)}",
                missing_ok=True,
            )
            if page is None:
                return found
            found.extend(page["results"])
            if len(found) >= page["total"] or not page["results"]:
                return found

    def search(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._call(
            "POST",
            f"/indexes/{urllib.parse.quote(index)}/search",
            body,
            timeout=self.search_timeout,
        )
        return result

    def rebuild(
        self, index: str, index_settings: dict[str, Any], documents: list[dict[str, Any]]
    ) -> None:
        """Fill a fresh index and swap it in, so searches never see a half one."""
        staging = f"{index}-next"
        self._drop(staging)
        self._wait(self._call("POST", "/indexes", {"uid": staging, "primaryKey": "id"}))
        self._wait(
            self._call("PATCH", f"/indexes/{urllib.parse.quote(staging)}/settings", index_settings)
        )
        for start in range(0, len(documents), PAGE):
            self._wait(
                self._call(
                    "PUT",
                    f"/indexes/{urllib.parse.quote(staging)}/documents",
                    documents[start : start + PAGE],
                ),
                timeout=300.0,
            )
        if self._call("GET", f"/indexes/{urllib.parse.quote(index)}", missing_ok=True) is None:
            self._wait(self._call("POST", "/indexes", {"uid": index, "primaryKey": "id"}))
        swap = self._call("POST", "/swap-indexes", [{"indexes": [index, staging]}])
        try:
            self._wait(swap)
        except SearchEngineUnavailable as error:
            # A key scoped to some indexes (a stack on a shared engine) cannot
            # read a swap task: it names two indexes. Tasks run in the order
            # they were queued, so the drop below still comes after the swap,
            # and the count after it says whether the swap happened.
            if str(error) != "search_http_404":
                raise
        self._drop(staging)
        # Counted through documents, not stats: a scoped key may read those.
        live = self._call("GET", f"/indexes/{urllib.parse.quote(index)}/documents?limit=0")
        if live.get("total") != len(documents):
            raise SearchEngineUnavailable("search_swap_unconfirmed")

    def _drop(self, index: str) -> None:
        # Deleting a missing index is a failed task, not a 404; ask first.
        if self._call("GET", f"/indexes/{urllib.parse.quote(index)}", missing_ok=True) is not None:
            self._wait(self._call("DELETE", f"/indexes/{urllib.parse.quote(index)}"))


def _differs(current: Any, desired: Any) -> bool:
    """Only what we set counts: the engine reads settings back with its defaults."""
    if isinstance(desired, dict):
        return not isinstance(current, dict) or any(
            _differs(current.get(key), value) for key, value in desired.items()
        )
    return bool(current != desired)


def engine() -> Engine | None:
    """The configured engine, or None when this deployment runs without one."""
    if not settings.SEARCH_URL or not settings.SEARCH_API_KEY:
        return None
    return Meilisearch(
        settings.SEARCH_URL, settings.SEARCH_API_KEY, settings.SEARCH_TIMEOUT_SECONDS
    )
