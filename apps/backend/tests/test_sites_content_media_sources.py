"""Pictures of a live record on the platform's host (ADR-080, „Uzupełnienie
PR1c"): `/media/<asset id>/<variant>` there also answers what a registered
public source of the platform's workspace says a visitor is shown — a breed's
picture on a product's own page — as one of our copies, never the original.

The source here is a test's own: no product's module is in the core. It reads
a table that forces row-level security, as a product's does, so the order of
the statements can be held — the tenant is set before the source is asked, in
the same transaction. The test database connects as the owner of the tables
and row-level security does not apply to it: that the application's role then
sees the source's rows, and only inside that setting, is shown on a running
stack.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from saas_core.modules.core.organizations import public_sources
from saas_core.modules.core.organizations.api import PublicSource
from saas_core.modules.shared.media.models import MediaAsset
from test_media_api import MemoryStorage
from test_sites_api import create_media_asset
from test_sites_content_reads import PNG, Publisher, _hero, _names, _read

pytestmark = pytest.mark.django_db

COPIES = ("thumbnail", "preview")
TABLES = (
    "organizations_organization",
    "sites_site",
    "sites_contententry",
    "media_mediaasset",
)
NOBODY = "00000000-0000-7000-8000-000000000000"


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> MemoryStorage:
    memory = MemoryStorage()
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.public_media.get_object_storage", lambda: memory
    )
    return memory


def _picture(
    storage: MemoryStorage, organization: Any, user: Any, copies: Iterable[str] = COPIES
) -> Any:
    """A picture of the media library with the copies the pipeline made."""
    asset = create_media_asset(organization, user)
    variants = {}
    for kind in copies:
        key = f"{organization.id}/variants/{asset.id}/{kind}.webp"
        variants[kind] = {"object_key": key, "content_type": "image/webp"}
        storage.objects[key] = (kind.encode(), "image/webp")
    MediaAsset.all_objects.filter(pk=asset.pk).update(variants=variants)
    storage.objects[asset.object_key] = (PNG, "image/png")
    return asset


class Records:
    """A module's live records that show pictures, as the registry of public
    sources sees them: which of a company's assets a visitor is shown."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.shown: set[UUID] = set()
        self.asked: list[UUID] = []
        # In the registry for this test only: a source left behind would
        # answer in every later test of the process.
        monkeypatch.setitem(
            public_sources._sources,
            "test.records",
            PublicSource("test.records", self.served, served_media=self.served),
        )

    def served(self, organization_id: UUID) -> set[UUID]:
        self.asked.append(organization_id)
        # A read of a table that forces row-level security, by the company:
        # what a product's source does with its own table.
        return set(
            MediaAsset.all_objects.filter(
                organization_id=organization_id, pk__in=sorted(self.shown)
            ).values_list("id", flat=True)
        )


def _copy(asset: Any, variant: str = "thumbnail") -> Any:
    return _read(f"media/{getattr(asset, 'id', asset)}/{variant}/")


def _original(asset: Any) -> Any:
    return _read(f"media/{getattr(asset, 'id', asset)}/")


def _answer(response: Any) -> tuple[int, bytes, str]:
    return response.status_code, response.content, response.get("Content-Type", "")


def test_a_live_records_picture_answers_on_the_platforms_host_as_a_copy_only(
    monkeypatch: pytest.MonkeyPatch, storage: MemoryStorage
) -> None:
    guide = Publisher("media-source")
    company = Publisher("media-source-company")
    records = Records(monkeypatch)
    of_record, kept, half_made = (
        _picture(storage, guide.organization, guide.user),
        _picture(storage, guide.organization, guide.user),
        _picture(storage, guide.organization, guide.user, copies=("thumbnail",)),
    )
    theirs = _picture(storage, company.organization, company.user)
    records.shown = {of_record.id, half_made.id, theirs.id}

    # A company's records are its own site's to show, never this address's.
    assert _copy(of_record).status_code == 404
    guide.enter()

    nobody = _copy(NOBODY)
    assert nobody.status_code == 404
    for variant in COPIES:
        served = _copy(of_record, variant)
        assert _answer(served) == (200, variant.encode(), "image/webp")
        assert served["Cache-Control"] == "public, max-age=31536000, immutable"
    # Never the original: no published entry names this picture.
    assert _answer(_original(of_record)) == _answer(_original(NOBODY))
    assert _original(of_record).status_code == 404
    assert _copy(of_record, "original").status_code == 404
    # A copy the pipeline never made is no address.
    assert _copy(half_made, "thumbnail").status_code == 200
    assert _copy(half_made, "preview").status_code == 404
    # The workspace's own picture that no record shows, another company's
    # that its record does show, and nobody's: one and the same answer.
    for asset in (kept, theirs):
        for variant in COPIES:
            assert _answer(_copy(asset, variant)) == _answer(nobody), (asset.id, variant)
    # Every question went to the source about the workspace and nobody else.
    assert set(records.asked) == {guide.organization.id}

    # Live: a record that stops showing its picture takes it off the host.
    records.shown = {half_made.id}
    assert _answer(_copy(of_record)) == _answer(nobody)
    assert _copy(half_made).status_code == 200


def test_a_published_entrys_picture_answers_as_before_beside_a_source(
    monkeypatch: pytest.MonkeyPatch, storage: MemoryStorage
) -> None:
    guide = Publisher("media-source-entry")
    records = Records(monkeypatch)
    in_entry = _picture(storage, guide.organization, guide.user)
    both = _picture(storage, guide.organization, guide.user)
    guide.entry("ze-zdjeciem", blocks=_hero(in_entry), media=[str(in_entry.id)])
    guide.entry("drugi", blocks=_hero(both), media=[str(both.id)])
    records.shown = {both.id}
    guide.enter()

    # An entry's picture: the original and the copies, on the entry's word.
    assert _answer(_original(in_entry)) == (200, PNG, "image/jpeg")
    assert _answer(_copy(in_entry, "preview")) == (200, b"preview", "image/webp")
    # Named by both: the original on the entry's word alone.
    assert _original(both).status_code == 200
    assert _copy(both).status_code == 200
    # The original asks no source: nothing a source says can open it.
    records.asked.clear()
    assert _original(in_entry).status_code == 200
    assert _original(NOBODY).status_code == 404
    assert records.asked == []


def test_the_tenant_is_set_before_the_source_is_asked(
    monkeypatch: pytest.MonkeyPatch, storage: MemoryStorage
) -> None:
    """A source reads its own tables, and they force row-level security.
    Asked before `SET LOCAL`, or after the transaction that set it ended, the
    application's role sees no row there and every such picture answers 404 —
    while the owner of the tables, which the tests connect as, sees them all.
    The order is what a test can hold."""
    guide = Publisher("media-source-order")
    company = Publisher("media-source-order-company")
    records = Records(monkeypatch)
    of_record = _picture(storage, guide.organization, guide.user)
    theirs = _picture(storage, company.organization, company.user)
    records.shown = {of_record.id, theirs.id}
    guide.enter()

    with CaptureQueriesContext(connection) as captured:
        served = _copy(of_record)
        refused = _copy(theirs)

    assert (served.status_code, refused.status_code) == (200, 404)
    statements = [query["sql"] for query in captured.captured_queries]
    # The source's own read: media by a list of identifiers.
    asked = [
        index
        for index, sql in enumerate(statements)
        if 'FROM "media_mediaasset"' in sql and '"media_mediaasset"."id" IN (' in sql
    ]
    assert len(asked) == 2
    for index in asked:
        tenant = max(
            (
                at
                for at, sql in enumerate(statements[:index])
                if sql.startswith("SET LOCAL app.organization_id")
            ),
            default=None,
        )
        assert tenant is not None, statements[index]
        assert _names(statements[tenant], guide.organization)
        # Still inside the transaction that set it: no block ended in between.
        assert not any(
            sql.startswith(("RELEASE SAVEPOINT", "ROLLBACK", "COMMIT"))
            for sql in statements[tenant:index]
        ), statements[index]
        assert _names(statements[index], guide.organization)
    # Nothing in either request names the other company: its picture is
    # refused by the workspace's own filters, not by a look at whose it is.
    for sql in statements:
        assert not _names(sql, company.organization), sql


def test_a_picture_costs_the_same_however_many_the_source_shows(
    monkeypatch: pytest.MonkeyPatch, storage: MemoryStorage
) -> None:
    """A product's source answers with every picture it shows — some hundreds
    of breeds — on each request, and a list page asks for dozens of
    thumbnails. One request is a fixed handful of statements whatever the
    size of that answer: the registry needs no second, cheaper question
    (measured on a stack with 374: ADR-080, „Uzupełnienie PR1c")."""
    guide = Publisher("media-source-cost")
    records = Records(monkeypatch)
    first = _picture(storage, guide.organization, guide.user)
    records.shown = {first.id}
    guide.enter()

    def statements() -> list[str]:
        with CaptureQueriesContext(connection) as captured:
            assert _copy(first).status_code == 200
        return [query["sql"] for query in captured.captured_queries]

    alone = statements()
    records.shown |= {create_media_asset(guide.organization, guide.user).id for _ in range(373)}
    among_many = statements()

    assert len(records.shown) == 374
    assert len(among_many) == len(alone)
    reads = [sql for sql in among_many if sql.startswith("SELECT")]
    # The door, the workspace's row and its site; then, with the tenant set,
    # one question to each source that serves pictures and the picture's row.
    assert [
        next(table for table in TABLES if f'FROM "{table}"' in sql)
        for sql in reads
        if "booking_resource" not in sql  # another source of this composition
    ] == [
        "organizations_organization",
        "organizations_organization",
        "sites_site",
        "media_mediaasset",
        "media_mediaasset",
    ]
    # A copy of a declared picture never searches the published snapshots.
    assert not any('"sites_contententrypublication"' in sql for sql in among_many)


def test_a_companys_own_site_serves_as_it_did(
    monkeypatch: pytest.MonkeyPatch, storage: MemoryStorage
) -> None:
    """The rule of a company's site (`public_media`) is the one copied here,
    not changed: its host serves its own records' pictures, and the
    platform's address never does."""
    company = Publisher("media-source-site")
    records = Records(monkeypatch)
    of_record = _picture(storage, company.organization, company.user)
    records.shown = {of_record.id}

    on_site = APIClient().get(
        f"/api/v1/public/site/media/{of_record.id}/thumbnail/", HTTP_HOST=company.host
    )
    assert _answer(on_site) == (200, b"thumbnail", "image/webp")
    assert _copy(of_record).status_code == 404
