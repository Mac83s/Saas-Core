"""The content import (ADR-079 pkt 34, „Uzupełnienie CT4”): a document of
existing content brought into one company's site by an operator's command,
through the services a person's panel calls."""

from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import OperationalError, connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from jsonschema import Draft202012Validator

from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    Organization,
    OrganizationAuditEntry,
)
from saas_core.modules.shared.media.models import MediaAsset, MediaAssetState
from saas_core.modules.shared.media.scanner import MalwareScannerUnavailable, MalwareVerdict
from saas_core.modules.shared.sites.content_import import (
    CREATE,
    HELD,
    KEPT,
    REFUSED,
    UNCHANGED,
    UPDATE,
    ImportReport,
    document_problems,
    format_report,
    run_import,
    text_fingerprint,
)
from saas_core.modules.shared.sites.content_import_schema import DOCUMENT_SCHEMA
from saas_core.modules.shared.sites.models import (
    ContentCollection,
    ContentEntry,
    ContentEntryPublication,
    ContentEntryState,
    ContentEntryTag,
    ContentImportRecord,
    ContentTag,
)
from test_sites_api import (
    CleanTemplateMediaScanner,
    TemplateMediaStorage,
    create_site,
    csrf_value,
    sites_client,
)
from test_sites_blog_languages import _feed, _get
from test_sites_collections import _verified_platform_domain
from test_sites_grant_commands import confirm_mfa
from test_sites_taxonomies import _one_hop, _status
from test_template_photos import enable_storage

pytestmark = pytest.mark.django_db

FIXTURE = Path(__file__).parent / "fixtures" / "content_import"


@pytest.fixture(autouse=True)
def a_company_in_five_languages(settings: Any) -> None:
    cache.clear()
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en", "de", "es", "ru")
    settings.CONTENT_TYPES_OFFERED = True


@pytest.fixture
def library(monkeypatch: pytest.MonkeyPatch) -> tuple[TemplateMediaStorage, Any]:
    storage, scanner = TemplateMediaStorage(), CleanTemplateMediaScanner()
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage", lambda: storage
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_malware_scanner", lambda: scanner
    )
    return storage, scanner


class Company:
    """A company with one site and the fixture's pictures beside a document."""

    def __init__(self, slug: str, directory: Path) -> None:
        self.client, self.organization, self.user = sites_client(slug=slug, role_key="owner")
        enable_storage(self.organization)
        self.site_id = str(create_site(self.client).data["id"])
        self.directory = directory
        if not (directory / "pictures").exists():
            shutil.copytree(FIXTURE / "pictures", directory / "pictures")

    def document(self) -> dict[str, Any]:
        document = json.loads((FIXTURE / "document.json").read_text(encoding="utf-8"))
        document["organization"] = self.organization.slug
        return dict(document)

    def run(self, document: dict[str, Any], *, apply: bool = False, **options: Any) -> ImportReport:
        membership = Membership.objects.select_related("role").get(
            organization=self.organization, user=self.user
        )
        with activate_tenant_context(context_from_membership(membership)):
            return run_import(
                copy.deepcopy(document), base_dir=self.directory, dry_run=not apply, **options
            )


def _lines(report: ImportReport, kind: str = "entry") -> dict[str, Any]:
    return {
        (f"{line.external_id}:{line.locale}" if line.locale else line.external_id): line
        for line in report.lines
        if line.kind == kind
    }


def _codes(line: Any) -> list[str]:
    return [note.code for note in line.notes]


def _counts() -> dict[str, int]:
    """How many rows every table holds — the whole database, not a list
    somebody has to keep."""
    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table in connection.introspection.table_names(cursor):
            cursor.execute(f'SELECT count(*) FROM "{table}"')  # noqa: S608 — table names
            counts[table] = int(cursor.fetchone()[0])
    return counts


def _entry(company: Company, external_id: str, locale: str = "pl") -> ContentEntry:
    record = ContentImportRecord.all_objects.get(
        organization=company.organization, kind="entry", external_id=external_id, locale=locale
    )
    return ContentEntry.with_removed.select_related("current_publication", "current_draft").get(
        pk=record.object_id
    )


def _send(client: Any, method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
    return getattr(client, method)(
        url,
        payload or {},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=f"k-{uuid4()}",
    )


# -- the dry run ----------------------------------------------------------------


def test_a_dry_run_writes_nothing_stores_nothing_and_scans_nothing(
    tmp_path: Path, library: Any
) -> None:
    storage, scanner = library
    company = Company("import-dry", tmp_path)
    before = _counts()

    with CaptureQueriesContext(connection) as queries:
        report = company.run(company.document())

    assert _counts() == before
    assert (storage.objects, storage.put_calls, scanner.calls) == ({}, [], 0)
    # Not one statement that could write: the plan only reads.
    written = [
        query["sql"]
        for query in queries.captured_queries
        if not query["sql"]
        .lstrip()
        .upper()
        .startswith(("SELECT", "SAVEPOINT", "RELEASE SAVEPOINT", "SET LOCAL"))
    ]
    assert written == []
    # …and holds no row: it is one long read, with every HTML converted and
    # every file hashed inside it.
    assert not any(
        "FOR UPDATE" in query["sql"] or "FOR NO KEY" in query["sql"] for query in queries
    )
    assert report.dry_run is True
    entries = _lines(report)
    # What a person is told before anything happens.
    assert {key: line.action for key, line in entries.items()} == {
        "post-1:pl": CREATE,
        "post-1:en": CREATE,
        "post-1:de": CREATE,
        "post-1:es": CREATE,
        "post-1:ru": CREATE,
        "post-2:pl": CREATE,
        "post-3:pl": HELD,
        "post-3:en": CREATE,
        # A dry run does not ask the scanner or open the file as a picture:
        # the broken one is refused by the real run.
        "post-4:pl": CREATE,
        "post-5:pl": CREATE,
        "post-6:en": REFUSED,
        "post-7:pl": CREATE,
        "post-7:fr": REFUSED,
        "post-8:pl": CREATE,
        "post-9:pl": REFUSED,
        "post-10:pl": REFUSED,
        "post-11:pl": REFUSED,
    }
    assert {key: _codes(line)[-1] for key, line in entries.items() if line.refused} == {
        "post-6:en": "picture_missing",
        "post-7:fr": "locale_not_enabled",
        "post-9:pl": "slug_taken",
        "post-10:pl": "term_unknown",
        "post-11:pl": "published_at_future",
    }
    # Addresses the document does not give are made from titles — a Cyrillic
    # one in Latin letters — and a second entry of the same title gets a number.
    assert {key: line.slug for key, line in entries.items() if line.slug and not line.refused} == {
        "post-1:pl": "jak-czesac-psa",
        "post-1:en": "how-to-brush-a-dog",
        "post-1:de": "wie-man-einen-hund-buerstet",
        "post-1:es": "como-cepillar-a-un-perro",
        "post-1:ru": "kak-raschesyvat-sobaku",
        "post-2:pl": "kapiel-psa",
        "post-3:pl": "pierwsza-wizyta-u-weterynarza",
        "post-3:en": "the-first-visit-to-the-vet",
        "post-4:pl": "spacer-w-deszczu",
        "post-5:pl": "szkic-zabawki-na-zime",
        "post-7:pl": "spacery-z-psem",
        "post-8:pl": "kapiel-psa-2",
    }
    # Which entries the converter changed, and what it lost.
    polish = entries["post-1:pl"]
    told = "\n".join(note.text for note in polish.notes)
    assert "heading_link_dropped ×1 (https://example.com/szczotki)" in told
    assert "[accepted by the document]" in told
    assert "table_span_flattened" in told and "underline_as_bold" in told
    assert polish.publication == "publish"
    # A translation made from an older source is named; one made from the
    # text the document holds is not.
    assert "translation_stale" in _codes(entries["post-1:de"])
    assert "translation_stale" not in _codes(entries["post-1:en"])
    assert "published_at_implausible" in _codes(entries["post-3:pl"])
    assert entries["post-3:pl"].publication == HELD
    assert "former_slug_live" in _codes(entries["post-2:pl"])
    assert report.pictures == {"known": 0, "new": 5, "bytes": 25502, "uploaded": 0, "failed": 0}
    text = format_report(report)
    assert text.startswith("DRY RUN — nothing was written, stored or scanned.")
    assert "REFUSED — nothing written for these (6):" in text
    assert company.organization.slug in text and str(company.organization.id) in text


def test_a_link_in_a_heading_holds_a_version_until_the_document_accepts_the_loss(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-losses", tmp_path)
    document = company.document()
    document["entries"] = document["entries"][:1]
    del document["entries"][0]["versions"][0]["accept_losses"]
    report = company.run(document, apply=True)
    polish = _lines(report)["post-1:pl"]
    assert (polish.action, polish.publication) == (HELD, HELD)
    assert "held_for_losses" in _codes(polish)
    assert any(
        note.level == "warning" and "heading_link_dropped" in note.text for note in polish.notes
    )
    # In as a draft — the words are all there to look at — and not public;
    # its translations, whose bodies lost nothing, are.
    assert _entry(company, "post-1").state == ContentEntryState.DRAFT
    assert _entry(company, "post-1", "en").state == ContentEntryState.PUBLISHED


# -- the import, and the import again --------------------------------------------


def test_the_fixture_comes_in_as_a_person_would_bring_it_and_twice_is_once(
    tmp_path: Path, library: Any
) -> None:
    storage, scanner = library
    company = Company("import-fixture", tmp_path)
    host = str(_verified_platform_domain(company.site_id).hostname)
    document = company.document()

    report = company.run(document, apply=True)

    assert report.counts() == {
        "type": {CREATE: 1},
        "category": {CREATE: 4, REFUSED: 1},
        "tag": {CREATE: 3},
        "entry": {CREATE: 10, HELD: 1, REFUSED: 6},
    }
    assert _codes(_lines(report)["post-4:pl"])[-1] == "picture_refused"
    assert report.pictures["uploaded"] == 4 and report.pictures["failed"] == 1
    # Every picture was put before the scanner, the broken one too.
    assert scanner.calls == 5
    # A refused entry left nothing behind — no row, no half of a group.
    assert not ContentImportRecord.all_objects.filter(external_id="post-4").exists()
    assert not ContentEntry.with_removed.filter(title="Spacer w deszczu").exists()

    # The type and its categories: three levels, five names, one address
    # given and the others made from the names.
    collection = ContentCollection.all_objects.get(site_id=company.site_id, key="poradnik")
    assert (collection.base_path, collection.locale_paths) == (
        "poradnik",
        {"en": "guide", "de": "ratgeber"},
    )
    terms = company.client.get(f"/api/v1/sites/collections/{collection.id}/terms/?kind=categories")
    rows = {row["name"]: row for row in terms.json()["terms"]}
    assert [(row["name"], row["depth"]) for row in terms.json()["terms"]] == [
        ("Pielęgnacja", 1),
        ("Sierść", 2),
        ("Czesanie", 3),
        ("Zdrowie", 1),
    ]
    care = rows["Pielęgnacja"]
    assert care["slugs"] == {
        "pl": "pielegnacja",
        "en": "care",
        "de": "pflege",
        "es": "cuidado",
        "ru": "ukhod",
    }
    # Names arrive as a person's text: the translation engine leaves them.
    assert {name["origin"] for name in care["names"].values()} == {"human"}
    assert rows["Zdrowie"]["slugs"]["en"] == "health"
    assert ContentTag.all_objects.get(pk=care["id"]).former_slugs == ["pielegnacja-psa"]
    tags = {tag.name: tag for tag in ContentTag.all_objects.filter(taxonomy__isnull=True)}
    assert set(tags) == {"Szczenięta", "Długa sierść", "Spacery"}
    assert tags["Długa sierść"].former_slugs == ["dlugowlose"]

    # One article in five languages: one group, each version its own entry.
    versions = {
        locale: _entry(company, "post-1", locale) for locale in ("pl", "en", "de", "es", "ru")
    }
    assert len({entry.translation_group for entry in versions.values()}) == 1
    polish, english = versions["pl"], versions["en"]
    assert all(entry.state == ContentEntryState.PUBLISHED for entry in versions.values())
    assert (polish.slug, polish.former_slugs) == ("jak-czesac-psa", ["czesanie-psa", "czesanie"])
    assert english.former_slugs == ["brushing-a-dog"]
    assert polish.author_name == english.author_name == "Anna Nowak"
    # Every version is filed under the entry's categories and tags.
    for entry in versions.values():
        filed = {link.tag.name for link in ContentEntryTag.all_objects.filter(entry=entry)}
        assert filed == {"Czesanie", "Długa sierść", "Szczenięta"}
    # The dates: when it was published, and when its text changed — both the
    # document's, neither tonight's.
    assert polish.published_at == datetime.fromisoformat("2023-03-14T08:30:00+01:00")
    assert polish.current_publication is not None and english.current_publication is not None
    assert polish.current_publication.snapshot["changed_at"] == "2025-02-01T10:00:00+01:00"
    # Left out, `changed_at` is the publication date.
    assert versions["es"].current_publication is not None
    assert versions["es"].current_publication.snapshot["changed_at"] == "2023-03-14T08:30:00+01:00"
    # Who wrote what: a person's original has no machine mark, a model's
    # translation has, and a person's title on a model's text is „mixed”.
    assert polish.current_publication.snapshot["origin"] == {
        "origin": "human",
        "machine": False,
        "reviewed": True,
    }
    assert english.current_publication.snapshot["origin"] == {
        "origin": "ai",
        "machine": True,
        "reviewed": False,
    }
    assert versions["es"].current_publication.snapshot["origin"]["origin"] == "mixed"
    assert versions["es"].current_publication.snapshot["origin"]["machine"] is True
    assert polish.current_draft is not None
    assert (polish.current_draft.origin, polish.current_draft.origin_ref) == (
        "import",
        "content-import:core-fixture",
    )
    # The fingerprints are kept as the document gave them, for every field —
    # one the core does not hold included — and the stale one is marked.
    kept = ContentImportRecord.all_objects.get(external_id="post-1", locale="en").fields
    given = document["entries"][0]["versions"][1]["fields"]
    assert kept["body"]["source_sha256"] == given["body"]["source_sha256"]
    assert kept["meta_description"] == given["meta_description"]
    assert (kept["title"]["origin"], kept["title"]["model"]) == ("ai", "fixture-translator-1")
    german = ContentImportRecord.all_objects.get(external_id="post-1", locale="de").fields
    assert german["body"]["stale"] is True and "stale" not in german["title"]

    # The pictures went through the library: the cover is the body's first
    # picture, the old `<img src>` is the document's file, with its words.
    blocks = polish.current_publication.snapshot["blocks"]
    figures = [
        node
        for block in blocks
        if block["block_type"] == "core.rich_text"
        for node in block["data"]["content"]
        if node["type"] == "figure"
    ]
    assert [figure["image"]["alt"] for figure in figures] == [
        "Pies czesany szczotką",
        "Szczotka do długiej sierści",
    ]
    assets = {str(asset.id): asset for asset in MediaAsset.all_objects.all()}
    assert len(assets) == 4
    assert {figure["image"]["asset_id"] for figure in figures} <= set(assets)
    assert all(asset.state == MediaAssetState.READY for asset in assets.values())
    assert set(polish.current_publication.snapshot["media_asset_ids"]) == {
        figure["image"]["asset_id"] for figure in figures
    }
    # A body given as blocks names its picture by file.
    walk = _entry(company, "post-7")
    assert walk.current_publication is not None
    assert len(walk.current_publication.snapshot["media_asset_ids"]) == 1

    # What was held, what is a draft, what was refused.
    assert _entry(company, "post-3").state == ContentEntryState.DRAFT
    assert _entry(company, "post-3").published_at is None
    assert _entry(company, "post-3", "en").state == ContentEntryState.PUBLISHED
    assert _entry(company, "post-5").state == ContentEntryState.DRAFT
    assert not ContentImportRecord.all_objects.filter(external_id="post-7", locale="fr").exists()
    assert _entry(company, "post-8").slug == "kapiel-psa-2"

    # The history names the operator, for every step and for the run.
    audit = OrganizationAuditEntry.objects.filter(organization=company.organization)
    assert set(
        audit.filter(action__startswith="sites.").values_list("actor_user_id", flat=True)
    ) == {company.user.id}
    run = audit.get(action="sites.content_import.run")
    assert run.metadata["source"] == "core-fixture"
    assert run.metadata["counts"]["entry"] == {CREATE: 10, HELD: 1, REFUSED: 6}
    assert audit.filter(action="sites.entry.former_slugs_recorded").count() == 3
    assert audit.filter(action="sites.taxonomy_term.created").count() == 7

    # A visitor: today's addresses answer, every old one is one 308.
    assert _status(host, "/poradnik/jak-czesac-psa/") == 200
    _one_hop(host, "/poradnik/czesanie/", "/poradnik/jak-czesac-psa/")
    _one_hop(host, "/en/guide/brushing-a-dog/", "/en/guide/how-to-brush-a-dog/")
    _one_hop(host, "/poradnik/kategoria/pielegnacja-psa/", "/poradnik/kategoria/pielegnacja/")
    assert _status(host, "/ru/poradnik/kak-raschesyvat-sobaku/") == 200
    assert _status(host, "/poradnik/pierwsza-wizyta-u-weterynarza/") == 404
    page = _get(host, "/poradnik/jak-czesac-psa/")
    assert page.data["article"]["published_at"] == "2023-03-14T07:30:00+00:00"
    assert page.data["article"]["updated_at"] == "2025-02-01T10:00:00+01:00"
    assert _get(host, "/en/guide/how-to-brush-a-dog/").data["machine_text"]["reviewed"] is False
    assert _get(host, "/poradnik/jak-czesac-psa/").data.get("machine_text") is None
    # Feeds and the sitemap carry the document's dates, not the import's.
    atom = _feed(host, "atom.xml").content.decode()
    assert "<published>2023-03-14T07:30:00+00:00</published>" in atom
    assert "<updated>2025-02-01T09:00:00+00:00</updated>" in atom
    assert timezone.now().date().isoformat() not in atom
    sitemap = _feed(host, "sitemap.xml").content.decode()
    assert "<lastmod>2025-02-01</lastmod>" in sitemap
    assert timezone.now().date().isoformat() not in sitemap

    # The same document again: nothing is written, anywhere.
    counted = _counts()
    stored = dict(storage.objects)
    with CaptureQueriesContext(connection) as queries:
        again = company.run(document, apply=True)
    after = _counts()
    # Not a row of the site is written or rewritten — the ledger's included.
    assert [
        query["sql"][:80]
        for query in queries.captured_queries
        if query["sql"].startswith(("INSERT", "UPDATE", "DELETE")) and '"sites_' in query["sql"]
    ] == []
    changed = {
        table: (counted[table], after[table]) for table in after if after[table] != counted[table]
    }
    # One line in the history says the run happened; that is all.
    assert changed == {
        "organizations_organizationauditentry": (
            counted["organizations_organizationauditentry"],
            counted["organizations_organizationauditentry"] + 1,
        )
    }
    assert storage.objects == stored
    assert again.counts()["entry"] == {UNCHANGED: 10, HELD: 1, REFUSED: 6}
    assert again.counts()["category"] == {UNCHANGED: 4, REFUSED: 1}
    assert again.counts()["tag"] == {UNCHANGED: 3}
    assert again.pictures["known"] == 4

    # And the whole company can still be erased, the ledger with it.
    from saas_core.modules.core.organizations.erasure import erase_organization

    receipt = erase_organization(
        organization=Organization.objects.get(pk=company.organization.pk),
        requested_by=None,
        reason="Synthetic test",
    )
    assert receipt.row_counts["sites.ContentImportRecord"] == 19
    assert not ContentImportRecord.all_objects.filter(organization=company.organization).exists()


def test_a_persons_later_edits_survive_a_newer_document_and_the_report_says_so(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-edits", tmp_path)
    client = company.client
    document = company.document()
    company.run(document, apply=True)
    first, bath, walks, second_bath, sketch = (
        _entry(company, external_id)
        for external_id in ("post-1", "post-2", "post-7", "post-8", "post-5")
    )
    english = _entry(company, "post-1", "en")

    # A person, in the panel, after the import: a title, a text (published),
    # an entry taken off the site, a version filed differently, a draft removed.
    assert (
        _send(
            client, "patch", f"/api/v1/sites/entries/{first.id}/metadata/", {"title": "Mój tytuł"}
        ).status_code
        == 200
    )
    edited = _send(
        client,
        "put",
        f"/api/v1/sites/entries/{bath.id}/draft/",
        {
            "expected_version": bath.version,
            "blocks": [
                {
                    "block_type": "core.rich_text",
                    "schema_version": 1,
                    "data": {"text": "Po mojemu."},
                }
            ],
        },
    )
    assert edited.status_code == 201, edited.data
    assert _send(client, "post", f"/api/v1/sites/entries/{bath.id}/publication/").status_code == 201
    assert _send(
        client, "delete", f"/api/v1/sites/entries/{second_bath.id}/publication/"
    ).status_code in (200, 204)
    assert (
        _send(
            client, "put", f"/api/v1/sites/entries/{english.id}/categories/", {"term_ids": []}
        ).status_code
        == 200
    )
    assert _send(client, "delete", f"/api/v1/sites/entries/{sketch.id}/").status_code in (200, 204)

    # A newer document: it changes what the person changed, what nobody
    # touched, fixes the date that was plainly wrong, and brings one entry more.
    newer = copy.deepcopy(document)
    # Without the entry whose picture only the real run can refuse: what is
    # left, the dry run foretells exactly.
    newer["entries"] = [entry for entry in newer["entries"] if entry["id"] != "post-4"]
    by_id = {entry["id"]: entry for entry in newer["entries"]}
    by_id["post-1"]["versions"][0]["title"] = "Tytuł z nowszego dokumentu"
    by_id["post-1"]["versions"][0]["excerpt"] = "Nowa zajawka."
    by_id["post-1"]["versions"][1]["title"] = "A newer English title"
    by_id["post-2"]["versions"][0]["body"] = {"html": "<p>Nowszy tekst z dokumentu.</p>"}
    by_id["post-8"]["versions"][0]["body"] = {"html": "<p>Nowszy tekst wycofanego wpisu.</p>"}
    by_id["post-7"]["versions"] = by_id["post-7"]["versions"][:1]
    by_id["post-7"]["versions"][0]["body"] = {"html": "<p>Trzy spacery dziennie.</p>"}
    by_id["post-7"]["versions"][0]["changed_at"] = "2026-09-01T10:00:00+02:00"
    by_id["post-3"]["versions"][0]["published_at"] = "2024-01-18T09:00:00+01:00"
    newer["entries"].append({
        "id": "post-12",
        "type": "poradnik",
        "versions": [
            {
                "locale": "pl",
                "title": "Zupełnie nowy wpis",
                "body": {"html": "<p>Dopisany później.</p>"},
                "status": "published",
                "published_at": "2026-10-01T08:00:00+02:00",
            }
        ],
    })

    planned = _lines(company.run(newer))
    report = company.run(newer, apply=True)
    lines = _lines(report)
    # The dry run said beforehand exactly what the run then did.
    assert {key: (line.action, line.publication) for key, line in planned.items()} == {
        key: (line.action, line.publication) for key, line in lines.items()
    }

    # The person's title stands; the excerpt nobody touched is updated, but
    # not published over the person's head.
    polish = lines["post-1:pl"]
    assert polish.action == KEPT and "title_kept" in _codes(polish)
    assert "not_republished" in _codes(polish) and polish.publication == "published"
    first = _entry(company, "post-1")
    assert (first.title, first.excerpt) == ("Mój tytuł", "Nowa zajawka.")
    assert first.current_publication is not None
    assert first.current_publication.snapshot["title"] == "Jak czesać psa, żeby to lubił"
    assert first.current_publication.sequence == 1
    # Its translations are told their source moved under them.
    assert "source_edited_in_panel" in _codes(lines["post-1:de"])
    # The person's text stands, the document's newer one is not applied.
    bathed = lines["post-2:pl"]
    assert bathed.action == KEPT and "body_kept" in _codes(bathed)
    bath = _entry(company, "post-2")
    assert bath.current_publication is not None
    assert bath.current_publication.snapshot["blocks"][0]["data"] == {"text": "Po mojemu."}
    # Withdrawn stays withdrawn; the newer text waits in its draft.
    withdrawn = lines["post-8:pl"]
    assert withdrawn.action == KEPT and "withdrawn_in_panel" in _codes(withdrawn)
    assert _entry(company, "post-8").state == ContentEntryState.WITHDRAWN
    # Filed by a person: left as filed; its new title, which nobody touched,
    # is in — unpublished, for the same reason as above.
    filed = lines["post-1:en"]
    assert "terms_kept" in _codes(filed) and filed.action == KEPT
    english = _entry(company, "post-1", "en")
    assert english.title == "A newer English title"
    assert not ContentEntryTag.all_objects.filter(
        entry=english, tag__taxonomy__isnull=False
    ).exists()
    # Removed stays removed.
    assert "removed_in_panel" in _codes(lines["post-5:pl"])
    assert _entry(company, "post-5").state == ContentEntryState.REMOVED
    # What nobody touched follows the document, and goes out again with the
    # document's date of change.
    walked = lines["post-7:pl"]
    assert (walked.action, walked.publication) == (UPDATE, "republish")
    walks = _entry(company, "post-7")
    assert walks.current_publication is not None
    assert walks.current_publication.sequence == 2
    assert walks.current_publication.snapshot["changed_at"] == "2026-09-01T10:00:00+02:00"
    assert walks.published_at == datetime.fromisoformat("2025-04-10T16:00:00+02:00")
    # The date is fixed: what was held goes out, under the date to show.
    vet = _entry(company, "post-3")
    assert (lines["post-3:pl"].action, lines["post-3:pl"].publication) == (UPDATE, "publish")
    assert vet.state == ContentEntryState.PUBLISHED
    assert vet.published_at == datetime.fromisoformat("2024-01-18T09:00:00+01:00")
    assert lines["post-12:pl"].action == CREATE
    assert _entry(company, "post-12").state == ContentEntryState.PUBLISHED
    text = format_report(report)
    assert "NEEDS A LOOK" in text and "[title_kept]" in text and "[body_kept]" in text

    # The newer document again: nothing more happens, and the person's
    # edits are still named.
    settled = company.run(newer, apply=True)
    assert all(line.action in (UNCHANGED, KEPT, REFUSED, HELD) for line in settled.lines), [
        (_n, line.action) for _n, line in _lines(settled).items()
    ]
    assert _entry(company, "post-1").title == "Mój tytuł"

    # Only when the operator names the entry does the document win.
    forced = company.run(newer, apply=True, overwrite_edits=["post-1", "post-2"])
    forced_lines = _lines(forced)
    assert forced_lines["post-1:pl"].action == UPDATE
    assert forced_lines["post-2:pl"].publication == "republish"
    assert _entry(company, "post-1").title == "Tytuł z nowszego dokumentu"
    bath = _entry(company, "post-2")
    assert bath.current_publication is not None
    assert "Nowszy tekst z dokumentu." in json.dumps(
        bath.current_publication.snapshot["blocks"], ensure_ascii=False
    )


def test_a_person_who_corrects_a_models_translation_does_not_erase_the_machine_mark(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-mark", tmp_path)
    document = company.document()
    document["entries"] = document["entries"][:1]
    company.run(document, apply=True)
    english = _entry(company, "post-1", "en")
    assert english.current_draft is not None
    blocks = copy.deepcopy(english.current_draft.blocks)
    blocks[0]["data"]["content"][1]["text"] = "How to pick a brush"
    saved = _send(
        company.client,
        "put",
        f"/api/v1/sites/entries/{english.id}/draft/",
        {"expected_version": english.version, "blocks": blocks},
    )
    assert saved.status_code == 201, saved.data
    assert (
        _send(
            company.client, "post", f"/api/v1/sites/entries/{english.id}/publication/"
        ).status_code
        == 201
    )
    english = _entry(company, "post-1", "en")
    assert english.current_publication is not None
    # Still, in part, a model's text — now with a person behind it.
    assert english.current_publication.snapshot["origin"] == {
        "origin": "mixed",
        "machine": True,
        "reviewed": True,
    }


# -- one tenant, named first -------------------------------------------------------


def _operator(company: Company) -> None:
    """The company's owner is also an operator of the platform here: staff,
    with a second factor — what the command asks of whoever it names."""
    company.user.is_staff = True
    company.user.save(update_fields=["is_staff"])
    confirm_mfa(company.user)


def _command(company: Company, document: dict[str, Any], *arguments: str, **options: Any) -> str:
    path = company.directory / "document.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    out = StringIO()
    call_command(
        "sites_import_content",
        str(path),
        *arguments,
        organization=options.pop("organization", str(company.organization.id)),
        operator=options.pop("operator", company.user.email),
        stdout=out,
        **options,
    )
    return out.getvalue()


def test_the_command_names_its_tenant_before_every_read_and_touches_no_other_company(
    tmp_path: Path, library: Any
) -> None:
    other_directory = tmp_path / "other"
    other_directory.mkdir()
    other = Company("import-other", other_directory)
    other_document = other.document()
    other_document["entries"] = other_document["entries"][:2]
    other.run(other_document, apply=True)
    company = Company("import-tenant", tmp_path)
    _operator(company)
    document = company.document()
    document["entries"] = document["entries"][:2]

    def of_other() -> dict[str, int]:
        return {
            model.__name__: model._base_manager.filter(organization=other.organization).count()
            for model in (
                ContentEntry.with_removed.model,
                ContentTag,
                ContentCollection,
                ContentImportRecord,
                ContentEntryPublication,
                MediaAsset,
                OrganizationAuditEntry,
            )
        } | {
            "entries": sorted(
                ContentEntry.with_removed.filter(organization=other.organization).values_list(
                    "title", "slug", "updated_at"
                )
            )
        }

    before = of_other()
    with CaptureQueriesContext(connection) as queries, pytest.raises(CommandError) as failed:
        _command(company, document, apply=True)
    # Exit code 1: some object was refused (the fixture's orphan category).
    assert failed.value.returncode == 1
    assert of_other() == before

    statements = [query["sql"] for query in queries.captured_queries]
    named = [sql for sql in statements if sql.startswith("SET LOCAL app.organization_id")]
    # Only ever this organization…
    assert named and all(str(company.organization.id) in sql for sql in named)
    assert not any(str(other.organization.id) in sql for sql in statements)
    # …and at the start of every transaction the import opens: in a test the
    # outermost transaction is the test's own, so each of the import's is a
    # savepoint at depth one, and the statement after it names the tenant.
    depth, checked = 0, 0
    for index, sql in enumerate(statements):
        if sql.startswith("SAVEPOINT"):
            depth += 1
            if depth == 1:
                assert statements[index + 1].startswith("SET LOCAL app.organization_id"), (
                    statements[index + 1]
                )
                checked += 1
        elif sql.startswith(("RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")):
            depth -= 1 if sql.startswith("RELEASE") else 0
    assert checked > 10
    # No table with a policy is read before the first naming.
    first = statements.index(named[0])
    guarded = ("sites_content", "media_mediaasset", "organizations_membership", "sites_site")
    assert not any(table in sql for sql in statements[:first] for table in guarded)


def test_the_command_refuses_what_is_ambiguous_before_reading_anything_else(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-refusals", tmp_path)
    stranger_directory = tmp_path / "stranger"
    stranger_directory.mkdir()
    stranger = Company("import-stranger", stranger_directory)
    document = company.document()
    before = _counts()
    # Whoever the history will name is an operator: staff, with two factors.
    with pytest.raises(CommandError) as no_staff:
        _command(company, document, apply=True)
    assert no_staff.value.returncode == 2 and "operatorskich" in str(no_staff.value)
    company.user.is_staff = True
    company.user.save(update_fields=["is_staff"])
    with pytest.raises(CommandError) as no_mfa:
        _command(company, document, apply=True)
    assert no_mfa.value.returncode == 2 and "MFA" in str(no_mfa.value)
    _operator(company)
    _operator(stranger)
    before = {**_counts(), **{}}

    def stopped(*arguments: str, **options: Any) -> str:
        with pytest.raises(CommandError) as failed:
            _command(company, options.pop("document", document), *arguments, **options)
        assert failed.value.returncode == 2
        return str(failed.value)

    # A document for another organization than the one the operator named.
    wrong = {**document, "organization": stranger.organization.slug}
    assert "The document is for the organization" in stopped(document=wrong, apply=True)
    # Somebody who is not a member of the organization named — also when the
    # organization does not exist: the two are not told apart.
    assert "członkostwa" in stopped(operator=stranger.user.email, apply=True)
    assert "członkostwa" in stopped(organization=str(uuid4()), apply=True)
    assert "identyfikator" in stopped(organization=company.organization.slug, apply=True)
    # A second site: the command does not guess.
    second = create_site(company.client, slug="second-site", idempotency_key="second")
    assert second.status_code == 201, second.data
    assert "name one with --site" in stopped(apply=True)
    assert "no such site" in stopped(apply=True, site=str(uuid4()))
    # Another language than the site's, and a document that is not one.
    assert "language" in stopped(
        document={**document, "default_locale": "en"}, site=company.site_id, apply=True
    )
    broken = {**document, "entries": [{"id": "x", "type": "poradnik", "versions": []}]}
    assert "entries „x”: versions" in stopped(document=broken, site=company.site_id, apply=True)
    # A problem names the entry, the language and the value — here an old
    # address in another script, which the product redirects by itself.
    cyrillic = copy.deepcopy(document)
    cyrillic["entries"][0]["versions"][4]["former_slugs"] = ["как-расчёсывать"]
    told = stopped(document=cyrillic, site=company.site_id, apply=True)
    assert "entries „post-1” (ru): former_slugs/0 — 'как-расчёсывать' does not match" in told
    assert "is named twice" in stopped(
        document={**document, "tags": [*document["tags"], document["tags"][0]]},
        site=company.site_id,
        apply=True,
    )
    after = _counts()
    assert {
        table: after[table] - before[table] for table in after if after[table] != before[table]
    } == {
        # The second site and its rows; nothing of an import.
        table: after[table] - before[table]
        for table in after
        if after[table] != before[table]
        and "contentimport" not in table
        and "contententry" not in table
    }
    assert not ContentImportRecord.all_objects.exists()
    assert not ContentEntry.with_removed.filter(organization=company.organization).exists()

    # With the site named, the dry run is the default: a report, no writes.
    document["categories"] = document["categories"][:4]
    printed = _command(
        company, {**document, "entries": document["entries"][:1]}, site=company.site_id
    )
    assert printed.startswith("DRY RUN")
    assert not ContentImportRecord.all_objects.exists()
    schema = StringIO()
    call_command("sites_import_content", schema=True, stdout=schema)
    assert json.loads(schema.getvalue()) == DOCUMENT_SCHEMA


# -- the guards a person meets -------------------------------------------------------


def test_a_switched_off_type_and_a_platform_that_offers_no_more_types_refuse_clearly(
    tmp_path: Path, library: Any, settings: Any
) -> None:
    company = Company("import-guards", tmp_path)
    document = company.document()
    document["entries"] = document["entries"][:2]
    # The site has a type already, and the platform offers no second one.
    blog = _send(
        company.client,
        "post",
        f"/api/v1/sites/{company.site_id}/collections/",
        {"key": "blog", "name": "Blog", "kind": "blog", "base_path": "blog"},
    )
    assert blog.status_code == 201, blog.data
    settings.CONTENT_TYPES_OFFERED = False
    for apply in (False, True):
        report = company.run(document, apply=apply)
        kind = _lines(report, "type")["poradnik"]
        assert kind.refused and _codes(kind) == ["content_types_not_offered"]
        assert all(line.refused for line in _lines(report).values())
        assert all(line.refused for line in _lines(report, "category").values())
    assert not ContentImportRecord.all_objects.exists()
    assert ContentCollection.all_objects.filter(site_id=company.site_id).count() == 1

    # Offered again, the type comes in; switched off afterwards, nothing more does.
    settings.CONTENT_TYPES_OFFERED = True
    company.run(document, apply=True)
    collection = ContentCollection.all_objects.get(site_id=company.site_id, key="poradnik")
    off = _send(company.client, "post", f"/api/v1/sites/collections/{collection.id}/switch-off/")
    assert off.status_code == 200, off.data
    changed = copy.deepcopy(document)
    changed["entries"][1]["versions"][0]["title"] = "Inny tytuł"
    report = company.run(changed, apply=True)
    assert _codes(_lines(report, "type")["poradnik"]) == ["content_type_archived"]
    assert all(_codes(line)[-1] == "type_refused" for line in _lines(report).values())
    assert _entry(company, "post-2").title == "Kąpiel psa"


class _Scanner:
    """Says of each picture what the test tells it to."""

    def __init__(self, verdicts: list[Any]) -> None:
        self.verdicts, self.calls = verdicts, 0

    def scan(self, content: bytes) -> MalwareVerdict:
        self.calls += 1
        verdict = self.verdicts.pop(0) if self.verdicts else MalwareVerdict.CLEAN
        if isinstance(verdict, Exception):
            raise verdict
        return verdict


def test_a_picture_the_scanner_refuses_or_cannot_judge_keeps_its_entry_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = TemplateMediaStorage()
    scanner = _Scanner([MalwareVerdict.INFECTED])
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_object_storage", lambda: storage
    )
    monkeypatch.setattr(
        "saas_core.modules.shared.media.services.get_malware_scanner", lambda: scanner
    )
    company = Company("import-scanner", tmp_path)
    document = company.document()
    by_id = {entry["id"]: entry for entry in document["entries"]}
    document["entries"] = [by_id["post-1"], by_id["post-2"], by_id["post-7"], by_id["post-8"]]

    # The first picture — the one in the text of post-1 — is refused by the
    # scanner: the three versions that show it are not written, and the two
    # that do not wait for their source rather than stand in for it. The
    # other entries are in.
    report = company.run(document, apply=True)
    lines = _lines(report)
    refused = lines["post-1:pl"]
    assert refused.refused and "the library refused it" in refused.notes[-1].text
    assert lines["post-1:en"].refused and lines["post-1:de"].refused
    assert _codes(lines["post-1:es"])[-1] == _codes(lines["post-1:ru"])[-1] == "source_refused"
    assert lines["post-2:pl"].action == CREATE
    assert not ContentImportRecord.all_objects.filter(external_id="post-1").exists()
    assert _entry(company, "post-2").state == ContentEntryState.PUBLISHED
    # Nothing of the refused picture is where a visitor could fetch it.
    assert not MediaAsset.all_objects.filter(
        state=MediaAssetState.READY, original_filename__icontains="szczotka"
    ).exists()

    # A scanner that does not answer: after three pictures in a row the run
    # stops asking, and says the entries wait.
    silent = MalwareScannerUnavailable("down")
    company_two_directory = tmp_path / "two"
    company_two_directory.mkdir()
    scanner.verdicts = [silent, silent, silent, silent, silent]
    scanner.calls = 0
    waiting = Company("import-scanner-down", company_two_directory)
    document_two = waiting.document()
    by_id = {entry["id"]: entry for entry in document_two["entries"]}
    document_two["entries"] = [
        by_id[key] for key in ("post-1", "post-2", "post-7", "post-4", "post-8")
    ]
    report = waiting.run(document_two, apply=True)
    lines = _lines(report)
    assert scanner.calls == 3
    assert "run again" in lines["post-1:pl"].notes[-1].text
    assert "run again" in lines["post-7:pl"].notes[-1].text
    assert "wait for the next run" in lines["post-4:pl"].notes[-1].text
    assert lines["post-8:pl"].action == CREATE
    assert not MediaAsset.all_objects.filter(
        organization=waiting.organization, state=MediaAssetState.READY
    ).exists()
    # The scanner is back: the second run brings exactly what waited.
    scanner.verdicts = []
    report = waiting.run(document_two, apply=True)
    lines = _lines(report)
    assert lines["post-1:pl"].action == CREATE and lines["post-7:pl"].action == CREATE
    assert lines["post-8:pl"].action == UNCHANGED
    assert _entry(waiting, "post-1").state == ContentEntryState.PUBLISHED


def test_a_deadlock_is_tried_again_and_anything_else_is_not(
    tmp_path: Path, library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from saas_core.modules.shared.sites import content_import

    company = Company("import-deadlock", tmp_path)
    document = company.document()
    by_id = {entry["id"]: entry for entry in document["entries"]}
    document["entries"] = [by_id["post-2"], by_id["post-8"]]
    monkeypatch.setattr(content_import.time, "sleep", lambda _seconds: None)
    real = content_import.publish_entry
    failures: list[Exception] = []

    class _State(Exception):
        sqlstate = "40P01"

    def deadlocked(**arguments: Any) -> Any:
        if len(failures) < 2:
            error = OperationalError("deadlock detected")
            error.__cause__ = _State()
            failures.append(error)
            raise error
        return real(**arguments)

    monkeypatch.setattr(content_import, "publish_entry", deadlocked)
    report = company.run(document, apply=True)
    # Stopped twice by the database, published on the third go — and said.
    assert report.retries == 2
    assert _entry(company, "post-2").state == ContentEntryState.PUBLISHED
    assert "retried after a deadlock: 2" in format_report(report)

    def broken(**_arguments: Any) -> Any:
        raise OperationalError("connection lost")

    monkeypatch.setattr(content_import, "publish_entry", broken)
    changed = copy.deepcopy(document)
    changed["entries"][0]["versions"][0]["body"] = {"html": "<p>Inaczej.</p>"}
    report = company.run(changed, apply=True)
    line = _lines(report)["post-2:pl"]
    # The text is in; its publication failed, and the entry is named. The
    # other entry is untouched by it.
    assert (line.action, line.publication) == (HELD, HELD)
    assert _codes(line)[-1] == "publication_failed"
    assert _lines(report)["post-8:pl"].action == UNCHANGED
    # The next run publishes what waited.
    monkeypatch.setattr(content_import, "publish_entry", real)
    report = company.run(changed, apply=True)
    assert _lines(report)["post-2:pl"].publication == "republish"
    bath = _entry(company, "post-2")
    assert bath.current_publication is not None
    assert "Inaczej." in json.dumps(bath.current_publication.snapshot["blocks"])


def test_the_plan_asks_the_database_no_more_for_a_longer_document(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-queries", tmp_path)
    document = company.document()
    by_id = {entry["id"]: entry for entry in document["entries"]}
    document["categories"] = document["categories"][:4]

    def with_entries(count: int) -> dict[str, Any]:
        longer = copy.deepcopy(document)
        longer["entries"] = []
        for index in range(count):
            entry = copy.deepcopy(by_id["post-2"])
            entry["id"] = f"copy-{index}"
            entry["versions"][0]["title"] = f"Kąpiel psa {index}"
            entry["versions"][0].pop("former_slugs")
            longer["entries"].append(entry)
        longer["tags"] = [
            {"id": f"tag-{index}", "names": {"pl": f"Temat {index}"}} for index in range(count)
        ]
        for index, entry in enumerate(longer["entries"]):
            entry["tags"] = [f"tag-{index}"]
        return longer

    def asked(found: dict[str, Any]) -> int:
        with CaptureQueriesContext(connection) as queries:
            company.run(found)
        return len(queries)

    # On an empty site, and on one that holds the content already: neither
    # the number of entries nor of terms changes how often the plan asks.
    # (One run first: what a process reads once and remembers is not counted.)
    company.run(with_entries(1))
    assert asked(with_entries(4)) == asked(with_entries(12))
    company.run(with_entries(12), apply=True)
    longer = with_entries(12)
    shorter = copy.deepcopy(longer)
    shorter["entries"], shorter["tags"] = shorter["entries"][:4], shorter["tags"][:4]
    assert asked(shorter) == asked(longer)


def test_the_plan_says_what_the_run_would_meet_outside_the_document(
    tmp_path: Path, library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from saas_core.content_protocol.policy import TranslationPolicy
    from saas_core.modules.shared.billing.models import EntitlementSnapshot
    from saas_core.modules.shared.sites import content_import

    company = Company("import-outside", tmp_path)
    document = company.document()
    by_id = {entry["id"]: entry for entry in document["entries"]}
    document["entries"] = [by_id["post-1"], by_id["post-2"], by_id["post-8"]]

    # A translation engine that is on: publishing originals may order
    # translations into the languages the document lacks — said beforehand.
    monkeypatch.setattr(
        content_import,
        "translation_policy",
        lambda **_arguments: TranslationPolicy(mode="review", reason=None, mass_publication_cap=20),
    )
    report = company.run(document)
    assert len(report.notices) == 1
    assert "de ×2, en ×2, es ×2, ru ×2" in report.notices[0]
    assert "BEFORE YOU RUN:" in format_report(report)
    monkeypatch.undo()
    assert company.run(document).notices == []

    # A company whose plan gives no media library: the entries with pictures
    # are refused by the plan already, and translations wait for their source.
    snapshot = EntitlementSnapshot.all_objects.get(organization=company.organization)
    snapshot.features["storage.enabled"] = False
    snapshot.save()
    lines = _lines(company.run(document))
    assert _codes(lines["post-1:pl"])[-1] == "library_unavailable"
    assert _codes(lines["post-1:ru"])[-1] == "source_refused"
    assert _codes(lines["post-2:pl"])[-1] == "library_unavailable"
    assert lines["post-8:pl"].action == CREATE
    snapshot.features["storage.enabled"] = True
    snapshot.save()

    # A version in a language the import did not make stands in its way —
    # said as that, not as a failed write.
    company.run(document, apply=True)
    polish = _entry(company, "post-8")
    made = _send(
        company.client,
        "post",
        f"/api/v1/sites/entries/{polish.id}/translations/",
        {"locale": "en", "slug": "bathing-again", "title": "By hand"},
    )
    assert made.status_code == 201, made.data
    newer = copy.deepcopy(document)
    newer["entries"][2]["versions"].append({
        "locale": "en",
        "title": "Bathing a dog, again",
        "body": {"html": "<p>From the document.</p>"},
        "status": "published",
        "published_at": "2025-08-01T09:00:00+02:00",
    })
    for apply in (False, True):
        lines = _lines(company.run(newer, apply=apply))
        assert _codes(lines["post-8:en"]) == ["version_exists"]
        assert lines["post-8:pl"].action == UNCHANGED
    assert ContentEntry.all_objects.get(slug="bathing-again").title == "By hand"


# -- what the review found ---------------------------------------------------------


def test_what_a_person_took_off_the_site_stays_off_whoever_published_it(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-off", tmp_path)
    document = company.document()
    document["entries"] = document["entries"][:1]
    accepted = document["entries"][0]["versions"][0].pop("accept_losses")
    company.run(document, apply=True)
    polish = _entry(company, "post-1")
    # Held by the import; published, and then withdrawn, by a person.
    assert polish.state == ContentEntryState.DRAFT
    url = f"/api/v1/sites/entries/{polish.id}/publication/"
    assert _send(company.client, "post", url).status_code == 201
    assert _send(company.client, "delete", url).status_code in (200, 204)
    document["entries"][0]["versions"][0]["accept_losses"] = accepted

    for apply in (False, True):
        line = _lines(company.run(document, apply=apply))["post-1:pl"]
        assert (line.action, line.publication) == (KEPT, KEPT)
        assert "withdrawn_in_panel" in _codes(line)
    assert _entry(company, "post-1").state == ContentEntryState.WITHDRAWN
    assert ContentEntryPublication.all_objects.filter(entry_id=polish.id).count() == 1


def test_a_date_of_change_ahead_of_now_publishes_nothing_again(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-future", tmp_path)
    document = company.document()
    document["entries"] = [entry for entry in document["entries"] if entry["id"] == "post-2"]
    document["entries"][0]["versions"][0]["changed_at"] = "2031-01-01T10:00:00+01:00"
    first = _lines(company.run(document, apply=True))["post-2:pl"]
    assert "changed_at_future" in _codes(first) and first.publication == "publish"
    bath = _entry(company, "post-2")
    assert bath.current_publication is not None
    # The publication date stands in for a date that cannot be right.
    assert bath.current_publication.snapshot["changed_at"] == "2022-06-01T12:00:00+02:00"
    for _run in range(2):
        again = _lines(company.run(document, apply=True))["post-2:pl"]
        assert (again.action, again.publication) == (UNCHANGED, "published")
    assert ContentEntryPublication.all_objects.filter(entry_id=bath.id).count() == 1


def test_only_fields_that_have_words_say_who_wrote_the_text(tmp_path: Path, library: Any) -> None:
    company = Company("import-empty-field", tmp_path)
    document = company.document()
    document["entries"] = [entry for entry in document["entries"] if entry["id"] == "post-2"]
    version = document["entries"][0]["versions"][0]
    version.pop("excerpt", None)
    version["origin"] = "human"
    version["fields"] = {"excerpt": {"origin": "ai", "model": "m"}}
    company.run(document, apply=True)
    bath = _entry(company, "post-2")
    assert bath.current_publication is not None and bath.current_draft is not None
    assert bath.current_publication.snapshot["origin"] == {
        "origin": "human",
        "machine": False,
        "reviewed": True,
    }
    assert sorted(bath.current_draft.units) == ["import/body", "import/title"]


def test_the_assistants_edit_of_an_imported_machine_text_keeps_the_mark(
    tmp_path: Path, library: Any
) -> None:
    from uuid import uuid7

    from saas_core.modules.core.organizations.context import acting_context
    from saas_core.modules.shared.sites.collections import publish_entry, save_entry_draft

    company = Company("import-assistant", tmp_path)
    document = company.document()
    document["entries"] = document["entries"][:1]
    company.run(document, apply=True)
    english = _entry(company, "post-1", "en")
    assert english.current_draft is not None
    membership = Membership.objects.select_related("role").get(
        organization=company.organization, user=company.user
    )
    person = context_from_membership(membership)
    assistant = acting_context(person, via="assistant", ref=f"conversation:{uuid7()}")
    blocks = copy.deepcopy(english.current_draft.blocks)
    blocks[0]["data"]["content"][1]["text"] = "Choosing a brush"
    with activate_tenant_context(assistant):
        saved, _created = save_entry_draft(
            entry_id=english.id,
            expected_version=english.version,
            blocks=blocks,
            idempotency_key="assistant-edit",
        )
    assert saved.units is not None
    assert saved.units["import/edit"]["provenance"]["origin"] == "ai"
    assert saved.units["import/body"]["provenance"]["origin"] == "ai"
    with activate_tenant_context(person):
        publish_entry(entry_id=english.id, idempotency_key="after-assistant")
    english = _entry(company, "post-1", "en")
    assert english.current_publication is not None
    assert english.current_publication.snapshot["origin"] == {
        "origin": "ai",
        "machine": True,
        "reviewed": False,
    }


def test_a_term_the_site_already_has_is_adopted_openly_and_left_as_it_is(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-adopt", tmp_path)
    client = company.client
    document = company.document()
    document["entries"] = document["entries"][:2]
    document["categories"] = document["categories"][:4]
    document["categories"][0]["slugs"] = {"pl": "pielegnacja-psow"}
    # The site has the type, a category and a tag of the document's names
    # already — a person's, each with a word of its own in English.
    made = _send(
        client,
        "post",
        f"/api/v1/sites/{company.site_id}/collections/",
        {"key": "poradnik", "name": "Poradnik", "kind": "blog", "base_path": "poradnik"},
    )
    assert made.status_code == 201, made.data
    type_id = made.data["id"]
    terms = f"/api/v1/sites/collections/{type_id}/terms/"
    care = _send(client, "post", terms, {"kind": "categories", "name": "Pielęgnacja"}).json()["id"]
    puppies = _send(client, "post", terms, {"kind": "tags", "name": "Szczenięta"}).json()["id"]
    assert (
        _send(client, "put", f"{terms}{care}/names/", {"names": {"en": "Grooming"}}).status_code
        == 200
    )
    assert (
        _send(client, "put", f"{terms}{puppies}/names/", {"names": {"en": "Pups"}}).status_code
        == 200
    )

    planned = company.run(document)
    done = company.run(document, apply=True)
    for report in (planned, done):
        categories, tags = _lines(report, "category"), _lines(report, "tag")
        assert _lines(report, "type")["poradnik"].action == UNCHANGED
        for line in (categories["cat-care"], tags["tag-puppies"]):
            # Said beforehand, with exactly what changes: the names it lacked.
            assert line.action == KEPT
            assert {"term_adopted", "name_kept"} <= set(_codes(line))
            assert line.changes[0] == "adopted"
            assert "name in de" in line.changes and "name in en" not in line.changes
        assert "address_kept" in _codes(categories["cat-care"])
        assert "former addresses" in categories["cat-care"].changes
        assert categories["cat-coat"].action == CREATE
        assert "NEEDS A LOOK" in format_report(report) and "[term_adopted]" in format_report(report)
    # One term each, as before; a person's English names and addresses stand.
    assert ContentTag.all_objects.filter(name="Pielęgnacja").count() == 1
    assert ContentTag.all_objects.filter(name="Szczenięta").count() == 1
    rows = {row["name"]: row for row in client.get(f"{terms}?kind=categories").json()["terms"]}
    assert rows["Pielęgnacja"]["names"]["en"]["text"] == "Grooming"
    assert rows["Pielęgnacja"]["names"]["de"]["text"] == "Pflege"
    assert rows["Pielęgnacja"]["slugs"]["en"] == "grooming"
    assert rows["Pielęgnacja"]["slugs"]["pl"] == "pielegnacja"
    assert rows["Sierść"]["parent_id"] == care
    tag_rows = {row["name"]: row for row in client.get(f"{terms}?kind=tags").json()["terms"]}
    assert tag_rows["Szczenięta"]["names"]["en"]["text"] == "Pups"
    # From now on it is in the ledger: the next run finds it there and says
    # no more than that the English name is a person's.
    again = _lines(company.run(document, apply=True), "category")["cat-care"]
    assert "term_adopted" not in _codes(again) and "name_kept" in _codes(again)


def test_terms_that_read_the_same_are_said_not_merged_or_refused_in_silence(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-same-names", tmp_path)
    document = company.document()
    by_id = {entry["id"]: entry for entry in document["entries"]}
    document["categories"] = document["categories"][:4]
    document["tags"] = [
        {"id": "tag-a", "names": {"pl": "Porady", "en": "Tips"}},
        # The same word in the site's language: one tag in the site.
        {"id": "tag-b", "names": {"pl": "porady", "en": "Advice"}},
        # Another tag that reads the same in English only: two tags.
        {"id": "tag-c", "names": {"pl": "Wskazówki", "en": "Tips"}},
    ]
    first, second = copy.deepcopy(by_id["post-2"]), copy.deepcopy(by_id["post-8"])
    first["tags"], second["tags"] = ["tag-a", "tag-b", "tag-c"], ["tag-b"]
    document["entries"] = [first, second]

    for apply in (False, True):
        report = company.run(document, apply=apply)
        tags = _lines(report, "tag")
        assert _codes(tags["tag-b"]) == ["term_merged"]
        assert "tag-a" in tags["tag-b"].notes[0].text
        assert _codes(tags["tag-c"]) == ["name_shared"]
        assert "[term_merged]" in format_report(report) and "[name_shared]" in format_report(report)
        assert all(not line.refused for line in _lines(report).values())
    found = {tag.name: tag for tag in ContentTag.all_objects.filter(taxonomy__isnull=True)}
    assert set(found) == {"Porady", "Wskazówki"}
    # Entries filed under either id carry the one tag; the merged id's own
    # English name is not applied.
    assert {
        link.tag.name
        for link in ContentEntryTag.all_objects.filter(entry=_entry(company, "post-2"))
    } >= {"Porady", "Wskazówki"}
    assert [
        link.tag.name
        for link in ContentEntryTag.all_objects.filter(
            entry=_entry(company, "post-8"), tag__taxonomy__isnull=True
        )
    ] == ["Porady"]
    collection = ContentCollection.all_objects.get(site_id=company.site_id, key="poradnik")
    rows = {
        row["name"]: row
        for row in company.client.get(
            f"/api/v1/sites/collections/{collection.id}/terms/?kind=tags"
        ).json()["terms"]
    }
    assert rows["Porady"]["names"]["en"]["text"] == "Tips"
    # Both read „Tips” in English; the second one's address there has a number.
    assert rows["Wskazówki"]["names"]["en"]["text"] == "Tips"
    assert (rows["Porady"]["slugs"]["en"], rows["Wskazówki"]["slugs"]["en"]) == ("tips", "tips-2")
    assert company.run(document, apply=True).counts()["tag"] == {UNCHANGED: 3}


def test_a_table_written_out_as_lines_holds_the_version_and_a_split_one_is_shown(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-tables", tmp_path)
    document = company.document()
    by_id = {entry["id"]: entry for entry in document["entries"]}
    document["categories"] = document["categories"][:4]
    wide, long = copy.deepcopy(by_id["post-2"]), copy.deepcopy(by_id["post-8"])
    cells = "".join(f"<td>k{index}</td>" for index in range(13))
    wide["versions"][0]["body"] = {"html": f"<table><tr>{cells}</tr><tr>{cells}</tr></table>"}
    rows = "".join(f"<tr><td>w{index}</td><td>x</td></tr>" for index in range(130))
    long["versions"][0]["body"] = {"html": f"<table>{rows}</table>"}
    document["entries"] = [wide, long]

    for apply in (False, True):
        report = company.run(document, apply=apply)
        lines = _lines(report)
        # Too wide for a table block: every row becomes a line of text. A
        # reader sees that, so it is held like a loss of content.
        held = lines["post-2:pl"]
        assert (held.action, held.publication) == (HELD, HELD)
        assert any(
            note.level == "warning" and "table_too_wide ×1 (13 columns)" in note.text
            for note in held.notes
        )
        # Split in two because of its length: published, and shown.
        split = lines["post-8:pl"]
        assert split.publication in ("publish", "published")
        assert any(note.level == "warning" and "table_split" in note.text for note in split.notes)
        text = format_report(report)
        assert "entry post-2 pl „Kąpiel psa”: [body_changed] body changed: table_too_wide" in text
        assert "entry post-8 pl „Kąpiel psa”: [body_split] body split: table_split" in text
    assert _entry(company, "post-2").state == ContentEntryState.DRAFT
    assert _entry(company, "post-8").state == ContentEntryState.PUBLISHED
    # The document accepts it: out it goes.
    wide["versions"][0]["accept_losses"] = ["table_too_wide"]
    assert _lines(company.run(document, apply=True))["post-2:pl"].publication == "publish"
    assert _entry(company, "post-2").state == ContentEntryState.PUBLISHED


def test_markup_in_a_plain_field_refuses_the_version_before_anything_is_written(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-markup", tmp_path)
    document = company.document()
    by_id = {entry["id"]: entry for entry in document["entries"]}
    document["categories"] = document["categories"][:4]
    document["categories"][3]["names"]["en"] = "<b>Health</b>"
    excerpt, title, plain = (copy.deepcopy(by_id[key]) for key in ("post-2", "post-8", "post-5"))
    excerpt["versions"][0]["excerpt"] = "<p>Ciepła woda i spokój.</p>"
    excerpt["categories"] = ["cat-care"]
    title["versions"][0]["title"] = "Kąpiel &amp; suszenie"
    # A sign that is no markup stays a sign.
    plain["versions"][0]["title"] = "Zabawki < 20 zł & inne"
    document["entries"] = [excerpt, title, plain]

    for apply in (False, True):
        report = company.run(document, apply=apply)
        lines = _lines(report)
        assert _codes(lines["post-2:pl"]) == ["markup_in_excerpt"]
        assert "„<p>”" in lines["post-2:pl"].notes[0].text
        assert _codes(lines["post-8:pl"]) == ["markup_in_title"]
        assert not lines["post-5:pl"].refused
        assert _codes(_lines(report, "category")["cat-health"]) == ["markup_in_name"]
    assert not ContentImportRecord.all_objects.filter(external_id__in=["post-2", "post-8"]).exists()
    assert _entry(company, "post-5").title == "Zabawki < 20 zł & inne"


def test_what_the_core_has_no_field_for_is_kept_with_its_words(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-extra", tmp_path)
    document = company.document()
    document["entries"] = document["entries"][:1]
    document["categories"] = document["categories"][:4]
    company.run(document, apply=True)

    def kept(kind: str, external_id: str, locale: str = "") -> dict[str, Any]:
        record = ContentImportRecord.all_objects.get(
            kind=kind, external_id=external_id, locale=locale
        )
        return dict(record.fields)

    assert kept("entry", "post-1", "pl")["seo_title"] == {
        "origin": "human",
        "text": "Czesanie psa krok po kroku",
    }
    english = kept("entry", "post-1", "en")["meta_description"]
    assert english["text"] == "How to brush a dog in ten minutes."
    assert english["origin"] == "ai" and len(english["source_sha256"]) == 64
    assert kept("category", "cat-care")["extra"] == {
        "description": {"pl": "Wszystko o pielęgnacji psa.", "en": "All about caring for a dog."}
    }
    # A newer document changes only those words: the ledger follows, and
    # nothing of the entry or the category is written or published.
    newer = copy.deepcopy(document)
    newer["entries"][0]["versions"][0]["fields"]["seo_title"]["text"] = "Jak czesać psa"
    newer["categories"][0]["fields"]["description"]["pl"] = "Nowy opis."
    polish = _entry(company, "post-1")
    report = company.run(newer, apply=True)
    line = _lines(report)["post-1:pl"]
    assert (line.action, line.changes, line.publication) == (
        UPDATE,
        ["record of origins"],
        "published",
    )
    assert _lines(report, "category")["cat-care"].changes == ["record of other fields"]
    assert kept("entry", "post-1", "pl")["seo_title"]["text"] == "Jak czesać psa"
    assert kept("category", "cat-care")["extra"]["description"]["pl"] == "Nowy opis."
    after = _entry(company, "post-1")
    assert (after.version, after.current_publication_id) == (
        polish.version,
        polish.current_publication_id,
    )
    # The core's own fields carry no `text` of their own.
    wrong = copy.deepcopy(document)
    wrong["entries"][0]["versions"][0]["fields"]["title"] = {"text": "x"}
    assert "fields/title" in document_problems(wrong)[0]


def test_what_an_earlier_run_made_and_is_gone_is_said_when_it_is_made_again(
    tmp_path: Path, library: Any
) -> None:
    company = Company("import-gone", tmp_path)
    document = company.document()
    by_id = {entry["id"]: entry for entry in document["entries"]}
    document["categories"] = document["categories"][:4]
    document["entries"] = [by_id["post-2"]]
    document["tags"].append({"id": "tag-unused", "names": {"pl": "Nieużywany"}})
    company.run(document, apply=True)
    # A person deletes a tag nothing carries; and the ledger remembers a
    # version whose entry was erased with its type (here: a row that is gone).
    collection = ContentCollection.all_objects.get(site_id=company.site_id, key="poradnik")
    unused = ContentTag.all_objects.get(name="Nieużywany")
    gone = _send(
        company.client, "delete", f"/api/v1/sites/collections/{collection.id}/terms/{unused.id}/"
    )
    assert gone.status_code in (200, 204), gone.data
    ContentImportRecord.all_objects.create(
        organization=company.organization,
        site_id=company.site_id,
        source="core-fixture",
        kind="entry",
        external_id="post-8",
        locale="pl",
        object_id=uuid4(),
        fields={},
        created_by=company.user,
    )
    document["entries"].append(by_id["post-8"])

    for apply in (False, True):
        report = company.run(document, apply=apply)
        tag, entry = _lines(report, "tag")["tag-unused"], _lines(report)["post-8:pl"]
        assert (tag.action, _codes(tag)) == (CREATE, ["made_again"])
        assert tag.notes[0].level == "warning"
        assert entry.action == CREATE and "made_again" in _codes(entry)
        assert "[made_again]" in format_report(report)
    assert ContentTag.all_objects.filter(name="Nieużywany").exists()
    assert _entry(company, "post-8").state == ContentEntryState.PUBLISHED


def test_the_source_version_is_written_first_and_a_stopped_write_begins_again_cleanly(
    tmp_path: Path, library: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from saas_core.modules.shared.sites import content_import
    from saas_core.modules.shared.sites.collections import group_source

    company = Company("import-source-first", tmp_path)
    document = company.document()
    document["categories"], document["tags"] = [], []
    # No version in the site's language, and the source is not the first
    # language of the list.
    document["entries"] = [
        {
            "id": "abroad",
            "type": "poradnik",
            "source_locale": "en",
            "versions": [
                {
                    "locale": locale,
                    "title": title,
                    "body": {"html": f"<p>{title}.</p>"},
                    "status": "published",
                    "published_at": "2025-01-01T10:00:00+01:00",
                    "origin": origin,
                }
                for locale, title, origin in (
                    ("de", "Nur auf Deutsch", "ai"),
                    ("en", "Written in English", "human"),
                )
            ],
        }
    ]
    # The database stops the first attempt half-way, after the entry rows
    # were made: the second attempt must not hold on to them.
    monkeypatch.setattr(content_import.time, "sleep", lambda _seconds: None)
    real = content_import.save_entry_draft
    stopped: list[int] = []

    class _State(Exception):
        sqlstate = "40P01"

    def deadlocked(**arguments: Any) -> Any:
        if not stopped:
            stopped.append(1)
            error = OperationalError("deadlock detected")
            error.__cause__ = _State()
            raise error
        return real(**arguments)

    monkeypatch.setattr(content_import, "save_entry_draft", deadlocked)
    report = company.run(document, apply=True)

    assert report.retries == 1
    assert {key: line.action for key, line in _lines(report).items()} == {
        "abroad:de": CREATE,
        "abroad:en": CREATE,
    }
    entries = list(ContentEntry.with_removed.filter(organization=company.organization))
    assert sorted(entry.locale for entry in entries) == ["de", "en"]
    english = _entry(company, "abroad", "en")
    assert english.state == ContentEntryState.PUBLISHED
    # The original is the group's oldest entry: what a translation engine
    # takes for the source where the site's own language has no version.
    assert group_source(entries, "pl") == english
    assert company.run(document, apply=True).counts()["entry"] == {UNCHANGED: 2}


# -- the schema ------------------------------------------------------------------------


def test_the_published_schema_is_the_one_the_command_reads() -> None:
    published = Path(__file__).parents[3] / "docs/architecture/content-import.v1.schema.json"
    assert json.loads(published.read_text(encoding="utf-8")) == DOCUMENT_SCHEMA
    Draft202012Validator.check_schema(DOCUMENT_SCHEMA)
    fixture = json.loads((FIXTURE / "document.json").read_text(encoding="utf-8"))
    assert document_problems(fixture) == []
    # The fingerprint the schema names is the one the fixture carries.
    polish, english = fixture["entries"][0]["versions"][:2]
    assert english["fields"]["title"]["source_sha256"] == text_fingerprint(polish["title"])
    assert english["fields"]["body"]["source_sha256"] == text_fingerprint(polish["body"]["html"])
