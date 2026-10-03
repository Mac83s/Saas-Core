"""Telling the translation engine that a page's public text changed
(`translation-sources.md` §8.1): from `publish_site` and from taking a page off
the site — never from a derived publication, a rollback or a translation write.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from saas_core.content_protocol.registry import notify_source_changed

PAGE_SOURCE_KEY = "sites.page"


def change_cause(context: Any) -> str:
    return "api_key" if getattr(context, "principal_kind", "") == "api_key" else "user"


def notify_pages_published(
    *,
    context: Any,
    previous: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any],
    default_locale: str,
) -> None:
    """The pages whose source text visitors read changed with this publication:
    a new version, or the source language's title or description."""
    before = _sources(previous, default_locale)
    changed = [
        UUID(page_id)
        for page_id, source in _sources(snapshot, default_locale).items()
        if before.get(page_id) != source
    ]
    if changed:
        notify_source_changed(
            context=context,
            source_key=PAGE_SOURCE_KEY,
            object_ids=changed,
            change="changed",
            cause=change_cause(context),
        )


def notify_page_deleted(*, context: Any, page_id: UUID) -> None:
    notify_source_changed(
        context=context,
        source_key=PAGE_SOURCE_KEY,
        object_ids=[page_id],
        change="deleted",
        cause=change_cause(context),
    )


def _sources(snapshot: Mapping[str, Any] | None, default_locale: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for page in (snapshot or {}).get("pages", []):
        if not isinstance(page, dict) or not page.get("page_id"):
            continue
        source = next(
            (
                item
                for item in page.get("locales", [])
                if isinstance(item, dict) and item.get("locale") == default_locale
            ),
            {},
        )
        found[str(page["page_id"])] = (
            page.get("version_id"),
            source.get("title"),
            source.get("description"),
        )
    return found
