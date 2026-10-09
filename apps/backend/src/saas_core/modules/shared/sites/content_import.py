"""Bringing a body of existing content into a site's content types — an
operator's service, not an API (ADR-079 pkt 34, „Uzupełnienie CT4”).

A document (`content_import_schema.DOCUMENT_SCHEMA`) names content types,
categories, tags and entries with their language versions, each under the id
it had where it came from. `run_import` reads it in two steps:

1. **The plan** — reads only. Everything the document asks for is checked
   against what the site holds: languages, types, slugs, dates, pictures on
   disk, the HTML converted to blocks and the blocks against their contracts,
   and — for what an earlier run brought — whether anybody changed it since.
   The result is the report: for every object what would be created, updated,
   left alone, kept as a person left it, held as a draft or refused, and why.
   A dry run stops here: it wrote nothing, stored nothing, scanned nothing.
2. **The writes** — through the services a person's panel calls, as the
   operator who runs the command, so every guard a person meets applies: the
   plan's limits, a switched-off type, block contracts, the namespace of a
   vocabulary, the media pipeline with its scanner, and the history, which
   names the operator. One transaction per document entry for its text, one
   per language version for its publication (a publication takes the rows of
   the terms it carries; one entry at a time keeps the order every other
   writer takes them in), each begun by naming the tenant. A failed entry
   leaves the others as they are and the report says which and why.

Three things only an import may do (pkt 34), each in one named place: a
term's and an entry's former addresses recorded without a publication
(`record_former_term_slugs`, `record_former_entry_slugs`), a publication's
`changed_at` taken from the document (`publish_entry(changed_at=…)`), and
where each text came from kept with its version (`ImportedText`).

Running the same document again changes nothing. A changed document updates
what changed — and only where the value is still the one an import wrote
(`ContentImportRecord`): a title, a text, a set of categories or a decision
to withdraw that a person made afterwards is kept, and the report says so.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import OperationalError, transaction
from django.utils import timezone
from jsonschema import Draft202012Validator
from rest_framework.exceptions import APIException

from saas_core.content_protocol.provenance import ORIGIN_AI, ORIGIN_HUMAN, ORIGIN_IMPORT
from saas_core.content_protocol.transliteration import slug_from_title
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import (
    require_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.media.api import (
    MalwareScannerUnavailable,
    approved_media_asset_id,
    materialize_approved_media_asset,
    unavailable_asset_ids,
)

from .block_contracts import validate_site_block
from .block_decoration import normalize_block
from .collections import (
    IMPORT_BODY,
    IMPORT_EXCERPT,
    IMPORT_TITLE,
    ImportedText,
    create_collection,
    create_entry,
    create_entry_translation,
    publish_entry,
    save_entry_draft,
    update_entry_metadata,
)
from .content_import_schema import DOCUMENT_SCHEMA, SCHEMA_NAME
from .content_type_limit import content_types_limit
from .entry_addresses import (
    ENTRY_SLUG_MAX,
    change_entry_slug,
    record_former_entry_slugs,
    valid_entry_slug,
)
from .html_blocks import LOST, HtmlConversionError, convert_html
from .language_versions import site_locales
from .models import (
    ContentCollection,
    ContentEntry,
    ContentEntryState,
    ContentEntryTag,
    ContentImportKind,
    ContentImportRecord,
    ContentSchemaType,
    Site,
)
from .rich_content import assert_unique_anchors
from .taxonomies import (
    change_term_address,
    create_term,
    list_terms,
    record_former_term_slugs,
    set_entry_categories,
    set_entry_tag_ids,
    set_term_names,
    update_term,
)
from .term_addresses import ENTRY_TERMS_MAX, KIND_CATEGORIES, KIND_TAGS

logger = logging.getLogger(__name__)

IMPORT_RUN = "sites.content_import.run"
ENTRY_PUBLISHED_AT_SET = "sites.entry.published_at_set"

CREATE = "create"
UPDATE = "update"
UNCHANGED = "unchanged"
KEPT = "kept"
HELD = "held"
REFUSED = "refused"
#: An action's weight when one line stands for several versions.
_WEIGHT = {UNCHANGED: 0, CREATE: 1, UPDATE: 1, KEPT: 2, HELD: 3, REFUSED: 4}

INFO = "info"
WARNING = "warning"
REFUSAL = "refusal"

#: A publication date older than this is taken for a mistake (a zero date of
#: another system), and one this far ahead for a plan — which an import does
#: not make: it publishes what the document says is published.
EARLIEST_PUBLICATION = datetime(1995, 1, 1, tzinfo=UTC)
CLOCK_SLACK = timedelta(minutes=5)
#: After this many pictures in a row the scanner did not answer for, the run
#: stops asking it: the entries that wait for a picture are reported and a
#: second run picks them up.
SCANNER_PATIENCE = 3
DEADLOCK_ATTEMPTS = 3
_DEADLOCK_STATES = frozenset({"40P01", "40001"})

_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)
ORIGINS = (ORIGIN_HUMAN, ORIGIN_AI, ORIGIN_IMPORT)
TEXT_FIELDS = ("title", "excerpt", "body")


class ImportStopped(Exception):
    """The document, or what it names, cannot be imported at all: nothing was
    read past the point and nothing written. Carries the lines to print."""

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = list(problems)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def text_fingerprint(text: str) -> str:
    """The fingerprint the schema names: SHA-256 of the text's UTF-8 bytes,
    exactly as the document holds it, in lower-case hex."""
    return hashlib.sha256(text.encode()).hexdigest()


@contextmanager
def _tenant_transaction(organization_id: UUID) -> Iterator[None]:
    """One transaction of the import, begun by naming the tenant: every table
    it touches forces row-level security, and a query that ran before the
    setting would see nothing — or, worse, be taken for „no such row”."""
    with transaction.atomic():
        set_local_organization_id(organization_id)
        yield


# -- the report ----------------------------------------------------------------


@dataclass(slots=True)
class Note:
    level: str
    code: str
    text: str

    def as_dict(self) -> dict[str, str]:
        return {"level": self.level, "code": self.code, "text": self.text}


@dataclass(slots=True)
class Line:
    """One object of the document and what the run does, or did, with it."""

    kind: str
    external_id: str
    locale: str = ""
    label: str = ""
    action: str = UNCHANGED
    #: What changes, by field.
    changes: list[str] = field(default_factory=list)
    #: An entry version: `publish`, `republish`, `published`, `draft`,
    #: `held`, `kept` or empty.
    publication: str = ""
    slug: str = ""
    notes: list[Note] = field(default_factory=list)

    def note(self, level: str, code: str, text: str) -> None:
        self.notes.append(Note(level, code, text))

    def refuse(self, code: str, text: str) -> None:
        self.action = REFUSED
        self.publication = ""
        self.changes = []
        self.note(REFUSAL, code, text)

    @property
    def refused(self) -> bool:
        return self.action == REFUSED

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.external_id,
            **({"locale": self.locale} if self.locale else {}),
            "label": self.label,
            "action": self.action,
            "changes": list(self.changes),
            **({"publication": self.publication} if self.publication else {}),
            **({"slug": self.slug} if self.slug else {}),
            "notes": [note.as_dict() for note in self.notes],
        }


@dataclass(slots=True)
class ImportReport:
    dry_run: bool
    source: str
    document_sha256: str
    organization: dict[str, str]
    site: dict[str, str]
    operator: str
    lines: list[Line] = field(default_factory=list)
    pictures: dict[str, int] = field(
        default_factory=lambda: {"known": 0, "new": 0, "bytes": 0, "uploaded": 0, "failed": 0}
    )
    timing: dict[str, float] = field(default_factory=dict)
    retries: int = 0

    def counts(self) -> dict[str, dict[str, int]]:
        found: dict[str, dict[str, int]] = {}
        for line in self.lines:
            kind = found.setdefault(line.kind, {})
            kind[line.action] = kind.get(line.action, 0) + 1
        return found

    @property
    def failed(self) -> bool:
        return any(line.refused for line in self.lines)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_NAME,
            "dry_run": self.dry_run,
            "source": self.source,
            "document_sha256": self.document_sha256,
            "organization": self.organization,
            "site": self.site,
            "operator": self.operator,
            "counts": self.counts(),
            "pictures": self.pictures,
            "retries": self.retries,
            "timing": self.timing,
            "lines": [line.as_dict() for line in self.lines],
        }


_ACTION_WORDS = {
    True: {
        CREATE: "would create",
        UPDATE: "would update",
        UNCHANGED: "unchanged",
        KEPT: "kept as a person left it",
        HELD: "would hold as a draft",
        REFUSED: "REFUSED",
    },
    False: {
        CREATE: "created",
        UPDATE: "updated",
        UNCHANGED: "unchanged",
        KEPT: "kept as a person left it",
        HELD: "held as a draft",
        REFUSED: "REFUSED",
    },
}


#: A version's publication, said after the fact.
_DONE = {"publish": "published now", "republish": "published again"}


def format_report(report: ImportReport) -> str:
    """The report as a person reads it: the numbers, then everything that
    needs a look — refusals, what is held, what a person's edit kept, stale
    translations, what the converter lost — and one line per object last."""
    words = _ACTION_WORDS[report.dry_run]
    out = [
        ("DRY RUN — nothing was written, stored or scanned." if report.dry_run else "IMPORT RUN"),
        f"source: {report.source}   document sha256: {report.document_sha256[:16]}…",
        f"organization: {report.organization['name']} ({report.organization['slug']}, "
        f"{report.organization['id']})",
        f"site: {report.site['name']} ({report.site['id']}), language {report.site['locale']}",
        f"operator: {report.operator}",
        "",
    ]
    for kind, counts in report.counts().items():
        parts = ", ".join(
            f"{words[action]} {count}"
            for action, count in sorted(counts.items(), key=lambda item: _WEIGHT[item[0]])
        )
        out.append(f"{kind:<9} {parts}")
    pictures = report.pictures
    out.append(
        f"pictures  {pictures['known']} already in the library, {pictures['new']} new "
        f"({pictures['bytes'] / 1024 / 1024:.1f} MB)"
        + (
            " — a dry run does not ask the scanner; its verdict comes with the real run"
            if report.dry_run
            else f"; stored {pictures['uploaded']}, failed {pictures['failed']}"
        )
    )
    if report.retries:
        out.append(f"retried after a deadlock: {report.retries}")
    if report.timing:
        out.append(
            "time      "
            + ", ".join(f"{name} {seconds:.2f} s" for name, seconds in report.timing.items())
        )
    for title, wanted in (
        ("REFUSED — nothing written for these", (REFUSAL,)),
        ("NEEDS A LOOK", (WARNING,)),
    ):
        found = [
            (line, note) for line in report.lines for note in line.notes if note.level in wanted
        ]
        if found:
            out += ["", f"{title} ({len(found)}):"]
            out += [f"  {_name(line)}: [{note.code}] {note.text}" for line, note in found]
    out += ["", "EVERY OBJECT:"]
    for line in report.lines:
        detail = ", ".join(line.changes)
        said = line.publication if report.dry_run else _DONE.get(line.publication, line.publication)
        publication = f" → {said}" if line.publication else ""
        out.append(
            f"  {_name(line)}: {words[line.action]}{publication}"
            + (f" [{detail}]" if detail else "")
            + (f"  /{line.slug}/" if line.slug else "")
        )
        out += [f"      · {note.text}" for note in line.notes if note.level == INFO]
    return "\n".join(out)


def _name(line: Line) -> str:
    locale = f" {line.locale}" if line.locale else ""
    label = f" „{line.label}”" if line.label else ""
    return f"{line.kind} {line.external_id}{locale}{label}"


# -- the plan ------------------------------------------------------------------


@dataclass(slots=True)
class _Picture:
    sha256: str
    path: Path
    content_type: str
    size: int
    asset_id: UUID
    known: bool
    #: Why the real run could not store it; empty while it can be used.
    failure: str = ""


@dataclass(slots=True)
class _Term:
    line: Line
    spec: Mapping[str, Any]
    kind: str
    type_key: str
    term_id: UUID | None = None
    record: ContentImportRecord | None = None
    create: bool = False
    rename: str = ""
    names: dict[str, str] = field(default_factory=dict)
    slugs: dict[str, str] = field(default_factory=dict)
    former: list[str] = field(default_factory=list)
    ledger: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _Version:
    line: Line
    spec: Mapping[str, Any]
    entry_spec: Mapping[str, Any]
    type_key: str
    locale: str
    entry: ContentEntry | None = None
    record: ContentImportRecord | None = None
    slug: str = ""
    change_slug: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    blocks: list[dict[str, Any]] | None = None
    write_body: bool = False
    media_ids: list[UUID] = field(default_factory=list)
    pictures: list[str] = field(default_factory=list)
    terms: bool = False
    former: list[str] = field(default_factory=list)
    publish: bool = False
    published_at: datetime | None = None
    changed_at: datetime | None = None
    set_published_at: bool = False
    imported: ImportedText | None = None
    ledger: dict[str, Any] = field(default_factory=dict)
    #: Only the ledger's row changes: what the document says of the text.
    record_only: bool = False


@dataclass(slots=True)
class _Namespace:
    """The slugs of one content type in one language: who answers under
    each, and whom each former one leads to."""

    live: dict[str, str] = field(default_factory=dict)
    former: dict[str, str] = field(default_factory=dict)

    def free(self, base: str, owner: str) -> str:
        slug, number = base, 2
        while self.live.get(slug, owner) != owner or self.former.get(slug, owner) != owner:
            slug, number = f"{base}-{number}", number + 1
        return slug


@dataclass(slots=True)
class _Plan:
    report: ImportReport
    site: Site
    organization_id: UUID
    base: Path
    overwrite: frozenset[str]
    locales: tuple[str, ...]
    now: datetime
    types: dict[str, ContentCollection | None] = field(default_factory=dict)
    type_lines: dict[str, Line] = field(default_factory=dict)
    type_specs: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    terms: dict[tuple[str, str], _Term] = field(default_factory=dict)
    entries: list[tuple[Mapping[str, Any], list[_Version]]] = field(default_factory=list)
    ledger: dict[tuple[str, str, str], ContentImportRecord] = field(default_factory=dict)
    rows: dict[UUID, ContentEntry] = field(default_factory=dict)
    filed: dict[UUID, set[UUID]] = field(default_factory=dict)
    namespaces: dict[tuple[str, str], _Namespace] = field(default_factory=dict)
    pictures: dict[str, _Picture] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)

    @property
    def default_locale(self) -> str:
        return str(self.site.default_locale)

    def namespace(self, type_key: str, locale: str) -> _Namespace:
        return self.namespaces.setdefault((type_key, locale), _Namespace())


def document_problems(document: Any) -> list[str]:
    """What keeps the document from being a `content-import.v1` at all."""
    validator = Draft202012Validator(DOCUMENT_SCHEMA)
    problems = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '(document)'}: {error.message}"
        for error in sorted(
            validator.iter_errors(document),
            key=lambda item: [str(part) for part in item.absolute_path],
        )
    ]
    if problems:
        return problems[:50]
    for name in ("types", "categories", "tags", "entries"):
        key = "key" if name == "types" else "id"
        seen: set[str] = set()
        for item in document.get(name, []):
            if item[key] in seen:
                problems.append(f"{name}: „{item[key]}” is named twice")
            seen.add(item[key])
    for entry in document.get("entries", []):
        locales = [version["locale"] for version in entry["versions"]]
        if len(locales) != len(set(locales)):
            problems.append(f"entries/{entry['id']}: a language is given twice")
    return problems


def run_import(
    document: Mapping[str, Any],
    *,
    base_dir: Path,
    site_id: UUID | None = None,
    dry_run: bool = True,
    overwrite_edits: Sequence[str] = (),
) -> ImportReport:
    """Plans the import of `document` into the active tenant's site and —
    unless `dry_run` — carries the plan out. The caller has activated the
    operator's tenant context; pictures are read under `base_dir`.

    `overwrite_edits` names entries (by their id in the document) whose
    fields a person changed after an earlier run and the document may now
    replace. Without it such a field is kept and reported."""
    context = require_tenant_context()
    problems = document_problems(document)
    if problems:
        raise ImportStopped(problems)
    started = time.monotonic()
    with _tenant_transaction(context.organization_id):
        plan = _open(document, context, base_dir, site_id, dry_run, frozenset(overwrite_edits))
        _plan_types(plan, document)
        _plan_terms(plan, document)
        _plan_entries(plan, document)
    plan.report.timing["plan"] = time.monotonic() - started
    if dry_run:
        return plan.report
    _apply(plan, context)
    plan.report.timing["total"] = time.monotonic() - started
    return plan.report


def _open(
    document: Mapping[str, Any],
    context: Any,
    base_dir: Path,
    site_id: UUID | None,
    dry_run: bool,
    overwrite: frozenset[str],
) -> _Plan:
    organization = Organization.objects.filter(pk=context.organization_id).first()
    if organization is None:
        raise ImportStopped(["The organization does not exist."])
    if str(document["organization"]) != str(organization.slug):
        raise ImportStopped([
            f"The document is for the organization „{document['organization']}”; the command "
            f"names „{organization.slug}” ({organization.name}). Nothing was read further."
        ])
    sites = list(
        Site.all_objects.filter(organization_id=organization.id).select_related("organization")
    )
    if site_id is not None:
        sites = [site for site in sites if site.id == site_id]
    if len(sites) != 1:
        raise ImportStopped([
            "The organization has no such site."
            if site_id is not None
            else f"The organization has {len(sites)} sites: name one with --site."
        ])
    site = sites[0]
    if str(document["default_locale"]) != str(site.default_locale):
        raise ImportStopped([
            f"The document's language is „{document['default_locale']}”, the site's is "
            f"„{site.default_locale}”."
        ])
    operator = User.objects.get(pk=context.actor_id)
    source = str(document["source"])
    plan = _Plan(
        report=ImportReport(
            dry_run=dry_run,
            source=source,
            document_sha256=_hash(document),
            organization={
                "id": str(organization.id),
                "slug": str(organization.slug),
                "name": str(organization.name),
            },
            site={"id": str(site.id), "name": str(site.name), "locale": str(site.default_locale)},
            operator=str(operator.email),
        ),
        site=site,
        organization_id=organization.id,
        base=base_dir.resolve(),
        overwrite=overwrite,
        locales=tuple(site_locales(site)),
        now=timezone.now(),
    )
    for record in ContentImportRecord.all_objects.filter(
        organization_id=organization.id, site_id=site.id, source=source
    ):
        plan.ledger[record.kind, record.external_id, record.locale] = record
    ids = [record.object_id for key, record in plan.ledger.items() if key[0] == "entry"]
    for row in ContentEntry.with_removed.select_related(
        "current_draft", "current_publication"
    ).filter(organization_id=organization.id, pk__in=ids):
        plan.rows[row.id] = row
    for entry_id, tag_id in ContentEntryTag.all_objects.filter(
        organization_id=organization.id, entry_id__in=ids
    ).values_list("entry_id", "tag_id"):
        plan.filed.setdefault(entry_id, set()).add(tag_id)
    return plan


# -- types


def _plan_types(plan: _Plan, document: Mapping[str, Any]) -> None:
    existing = {
        str(row.key): row
        for row in ContentCollection.all_objects.filter(
            organization_id=plan.organization_id, site_id=plan.site.id
        )
    }
    wanted = {str(item["key"]): item for item in document.get("types", [])}
    named = list(wanted)
    for entry in document.get("entries", []):
        if entry["type"] not in named:
            named.append(str(entry["type"]))
    for item in document.get("categories", []):
        if item["type"] not in named:
            named.append(str(item["type"]))
    for key in named:
        spec = wanted.get(key, {"key": key})
        line = Line(kind="type", external_id=key, label=str(spec.get("name", "")))
        plan.type_lines[key] = line
        plan.type_specs[key] = spec
        plan.report.lines.append(line)
        row = existing.get(key)
        plan.types[key] = row
        if row is not None:
            line.label = str(row.name)
            if row.archived_at is not None:
                line.refuse(
                    "content_type_archived",
                    "This content type is switched off. Switch it on in the panel first: "
                    "its entries are neither written nor published while it is off.",
                )
            continue
        if "name" not in spec or "base_path" not in spec:
            line.refuse(
                "type_unknown",
                "The site has no content type with this key, and the document does not say "
                "how to make one (`name`, `base_path`).",
            )
            continue
        limit = content_types_limit(plan.site)
        if not limit.allowed:
            line.refuse(str(limit.code), str(limit.message))
            continue
        line.action = CREATE
        line.changes = [f"address /{spec['base_path']}/"]
    for (key, locale), namespace in _slugs_in_use(plan, existing).items():
        plan.namespaces[key, locale] = namespace


def _slugs_in_use(
    plan: _Plan, existing: Mapping[str, ContentCollection]
) -> dict[tuple[str, str], _Namespace]:
    """Every slug the entries of the document's types hold today, by type
    and language — one query, whatever the number of entries."""
    keys = {row.id: key for key, row in existing.items() if key in plan.types}
    found: dict[tuple[str, str], _Namespace] = {}
    for entry_id, collection_id, locale, slug, former in ContentEntry.all_objects.filter(
        organization_id=plan.organization_id, collection_id__in=list(keys)
    ).values_list("id", "collection_id", "locale", "slug", "former_slugs"):
        namespace = found.setdefault((keys[collection_id], str(locale)), _Namespace())
        namespace.live[str(slug)] = str(entry_id)
        for item in former or []:
            namespace.former[str(item)] = str(entry_id)
    return found


# -- terms


def _plan_terms(plan: _Plan, document: Mapping[str, Any]) -> None:
    first_type = next(
        (key for key, line in plan.type_lines.items() if not line.refused),
        "",
    )
    current: dict[tuple[str, str], Any] = {}
    for key, row in plan.types.items():
        if row is None or plan.type_lines[key].refused:
            continue
        for found in list_terms(collection_id=row.id, kind=KIND_CATEGORIES).terms:
            current[key, str(found.term.id)] = found
    if first_type and plan.types.get(first_type) is not None:
        row = plan.types[first_type]
        assert row is not None
        for found in list_terms(collection_id=row.id, kind=KIND_TAGS).terms:
            current["", str(found.term.id)] = found
    for kind, name in ((ContentImportKind.CATEGORY, "categories"), (ContentImportKind.TAG, "tags")):
        for spec in document.get(name, []):
            type_key = str(spec["type"]) if kind == ContentImportKind.CATEGORY else first_type
            term = _plan_term(plan, str(kind), spec, type_key, current)
            plan.terms[str(kind), str(spec["id"])] = term
            plan.report.lines.append(term.line)


def _plan_term(
    plan: _Plan,
    kind: str,
    spec: Mapping[str, Any],
    type_key: str,
    current: Mapping[tuple[str, str], Any],
) -> _Term:
    names = {str(locale): str(name).strip() for locale, name in spec["names"].items()}
    default = plan.default_locale
    line = Line(kind=kind, external_id=str(spec["id"]), label=names.get(default, ""))
    term = _Term(line=line, spec=spec, kind=kind, type_key=type_key)
    if default not in names:
        line.refuse("name_missing", f"No name in the site's language ({default}).")
        return term
    if not type_key or plan.type_lines[type_key].refused:
        line.refuse("type_refused", "Its content type is refused (see the type's line).")
        return term
    parent = spec.get("parent")
    if parent is not None:
        above = plan.terms.get((str(ContentImportKind.CATEGORY), str(parent)))
        if above is None or above.line.refused or above.type_key != type_key:
            line.refuse(
                "parent_unknown",
                f"The category above it, „{parent}”, is not named earlier in the document "
                "for the same type, or is refused.",
            )
            return term
    record = plan.ledger.get((kind, str(spec["id"]), ""))
    found = (
        current.get((type_key if kind == ContentImportKind.CATEGORY else "", str(record.object_id)))
        if record is not None
        else None
    )
    wanted_slugs = {str(locale): str(slug) for locale, slug in (spec.get("slugs") or {}).items()}
    for locale in sorted((set(names) | set(wanted_slugs)) - set(plan.locales)):
        line.note(
            WARNING,
            "locale_not_enabled",
            f"The site has no language „{locale}”: its name and address are left out.",
        )
        names.pop(locale, None)
        wanted_slugs.pop(locale, None)
    term.ledger = {
        "names": {locale: _hash(name) for locale, name in names.items()},
        "slugs": dict(wanted_slugs),
    }
    if found is None:
        term.create = True
        term.names = {locale: name for locale, name in names.items() if locale != default}
        term.slugs = wanted_slugs
        term.former = [str(slug) for slug in spec.get("former_slugs") or []]
        line.action = CREATE
        line.changes = [f"names in {', '.join(sorted(names))}"]
        if record is not None:
            line.note(INFO, "made_again", "What an earlier run made is gone; it is made again.")
        return term
    assert record is not None
    term.term_id, term.record = found.term.id, record
    written = record.fields.get("names") or {}
    for locale, name in names.items():
        have = (
            found.term.name
            if locale == default
            else (found.names[locale].text if locale in found.names else "")
        )
        if have == name:
            continue
        if have and _hash(have) != written.get(locale):
            line.action = KEPT
            line.note(
                WARNING,
                "name_kept",
                f"The name in {locale} was changed in the panel („{have}”); the document's "
                f"„{name}” is not applied.",
            )
            term.ledger["names"][locale] = written.get(locale, "")
        elif locale == default:
            term.rename = name
        else:
            term.names[locale] = name
    asked = record.fields.get("slugs") or {}
    for locale, slug in wanted_slugs.items():
        have = str(found.slugs.get(locale, ""))
        if have == slug:
            continue
        if asked.get(locale) == slug or (locale in asked and have != asked[locale]):
            # Already asked for once, and it is something else today: a
            # person's address (or one the vocabulary could not give).
            line.note(
                INFO, "address_kept", f"The address in {locale} stays „{have}” (asked: „{slug}”)."
            )
            continue
        term.slugs[locale] = slug
    have_former = {str(item) for item in found.term.former_slugs or []}
    term.former = [
        str(slug) for slug in spec.get("former_slugs") or [] if str(slug) not in have_former
    ]
    if term.rename or term.names or term.slugs or term.former:
        if line.action != KEPT:
            line.action = UPDATE
        line.changes = [
            *(["name"] if term.rename else []),
            *(f"name in {locale}" for locale in sorted(term.names)),
            *(f"address in {locale}" for locale in sorted(term.slugs)),
            *(["former addresses"] if term.former else []),
        ]
    return term


# -- entries


def _plan_entries(plan: _Plan, document: Mapping[str, Any]) -> None:
    entries = document.get("entries", [])
    for entry_spec in entries:
        versions = [_start_version(plan, entry_spec, spec) for spec in entry_spec["versions"]]
        plan.entries.append((entry_spec, versions))
    # Addresses the document names first, in document order; then the ones
    # made from titles, which keep clear of all of those.
    for _spec, versions in plan.entries:
        for version in versions:
            _plan_named_slug(plan, version)
    for _spec, versions in plan.entries:
        for version in versions:
            _plan_former_slugs(plan, version)
    for entry_spec, versions in plan.entries:
        for version in versions:
            _plan_derived_slug(plan, version)
        source = _source_version(plan, entry_spec, versions)
        for version in versions:
            if not version.line.refused:
                _plan_version(plan, version, source)
        if source is not None and any(
            note.code in ("body_kept", "title_kept", "excerpt_kept") for note in source.line.notes
        ):
            for version in versions:
                if version is not source and not version.line.refused:
                    version.line.note(
                        WARNING,
                        "source_edited_in_panel",
                        f"The {source.locale} version was edited in the panel after the "
                        "import: this translation was made from the text before that edit.",
                    )
        plan.report.lines.extend(version.line for version in versions)
    known = [picture.asset_id for picture in plan.pictures.values()]
    missing = unavailable_asset_ids(organization_id=plan.organization_id, asset_ids=known)
    for picture in plan.pictures.values():
        picture.known = picture.asset_id not in missing
        plan.report.pictures["known" if picture.known else "new"] += 1
        if not picture.known:
            plan.report.pictures["bytes"] += picture.size


def _owner(version: _Version) -> str:
    """Who holds a slug in a namespace: the entry's row, or — before it
    exists — its place in the document."""
    if version.entry is not None:
        return str(version.entry.id)
    return f"{version.entry_spec['id']}:{version.locale}"


def _start_version(plan: _Plan, entry_spec: Mapping[str, Any], spec: Mapping[str, Any]) -> _Version:
    locale, type_key = str(spec["locale"]), str(entry_spec["type"])
    line = Line(
        kind="entry",
        external_id=str(entry_spec["id"]),
        locale=locale,
        label=str(spec["title"]).strip(),
        action=CREATE,
    )
    version = _Version(
        line=line, spec=spec, entry_spec=entry_spec, type_key=type_key, locale=locale
    )
    record = plan.ledger.get(("entry", str(entry_spec["id"]), locale))
    row = plan.rows.get(record.object_id) if record is not None else None
    if record is not None and row is not None:
        version.record, version.entry, version.slug = record, row, str(row.slug)
        line.action, line.slug = UNCHANGED, str(row.slug)
    if plan.type_lines[type_key].refused:
        line.refuse("type_refused", "Its content type is refused (see the type's line).")
    elif locale not in plan.locales:
        line.refuse(
            "locale_not_enabled",
            f"The site has no language „{locale}”. Switch it on in the panel, then run again.",
        )
    elif row is not None and row.state == ContentEntryState.REMOVED:
        line.action = KEPT
        line.note(
            WARNING,
            "removed_in_panel",
            "A person removed this entry in the panel after an earlier run; it is not made again.",
        )
    return version


def _skipped(version: _Version) -> bool:
    return version.line.refused or (
        version.entry is not None and version.entry.state == ContentEntryState.REMOVED
    )


def _plan_named_slug(plan: _Plan, version: _Version) -> None:
    if _skipped(version):
        return
    wanted = str(version.spec.get("slug") or "")
    namespace = plan.namespace(version.type_key, version.locale)
    owner = _owner(version)
    if version.entry is not None:
        if not wanted or wanted == version.slug:
            return
        before = (version.record.fields.get("slug") or {}) if version.record else {}
        if before.get("asked") == wanted:
            # Asked for before, and the entry has another address since: a
            # person's, or one the type could not give.
            return
        if before.get("written") not in (None, version.slug) and not _may_overwrite(plan, version):
            version.line.note(
                WARNING,
                "slug_kept",
                f"The address was changed in the panel (/{version.slug}/); the document's "
                f"/{wanted}/ is not applied.",
            )
            _kept(version.line)
            return
        if (
            namespace.live.get(wanted, owner) != owner
            or namespace.former.get(wanted, owner) != owner
        ):
            version.line.note(
                WARNING,
                "slug_taken",
                f"/{wanted}/ belongs to another entry of the type; the address stays "
                f"/{version.slug}/.",
            )
            return
        namespace.live.pop(version.slug, None)
        namespace.live[wanted] = owner
        version.change_slug, version.slug = True, wanted
        return
    if not wanted:
        return
    if namespace.live.get(wanted, owner) != owner:
        version.line.refuse(
            "slug_taken",
            f"Another entry of the type answers under /{wanted}/ in {version.locale} "
            "(in the site or earlier in this document).",
        )
    elif namespace.former.get(wanted, owner) != owner:
        version.line.refuse(
            "slug_former",
            f"/{wanted}/ redirects to another entry of the type today. A person takes such an "
            "address over in the panel, after a look at what stops.",
        )
    else:
        namespace.live[wanted] = owner
        version.slug = wanted


def _plan_former_slugs(plan: _Plan, version: _Version) -> None:
    if _skipped(version):
        return
    namespace = plan.namespace(version.type_key, version.locale)
    owner = _owner(version)
    have = {str(item) for item in (version.entry.former_slugs if version.entry else None) or []}
    for raw in version.spec.get("former_slugs") or []:
        slug = str(raw)
        if slug in have or slug == version.slug or slug in version.former:
            continue
        if namespace.live.get(slug, owner) != owner:
            version.line.note(
                WARNING,
                "former_slug_live",
                f"The old address /{slug}/ is today's address of another entry: it cannot "
                "redirect here, and is left out.",
            )
        elif namespace.former.get(slug, owner) != owner:
            version.line.note(
                WARNING,
                "former_slug_claimed",
                f"The old address /{slug}/ redirects to another entry already; left out.",
            )
        else:
            namespace.former[slug] = owner
            version.former.append(slug)


def _plan_derived_slug(plan: _Plan, version: _Version) -> None:
    if _skipped(version) or version.slug:
        return
    base = slug_from_title(str(version.spec["title"]), max_length=ENTRY_SLUG_MAX - 4)
    if not base or not valid_entry_slug(base):
        version.line.refuse(
            "slug_missing",
            "The version has no slug and its title gives none (no letters or digits).",
        )
        return
    namespace = plan.namespace(version.type_key, version.locale)
    owner = _owner(version)
    version.slug = namespace.free(base, owner)
    namespace.live[version.slug] = owner
    version.line.note(INFO, "slug_derived", f"address made from the title: /{version.slug}/")


def _source_version(
    plan: _Plan, entry_spec: Mapping[str, Any], versions: Sequence[_Version]
) -> _Version | None:
    wanted = str(entry_spec.get("source_locale") or plan.default_locale)
    return next((version for version in versions if version.locale == wanted), None)


def _may_overwrite(plan: _Plan, version: _Version) -> bool:
    return str(version.entry_spec["id"]) in plan.overwrite


def _field_facts(spec: Mapping[str, Any], name: str) -> dict[str, str]:
    """Who wrote a field and from what, as the document says: the field's own
    word, else the version's."""
    own = (spec.get("fields") or {}).get(name) or {}
    origin = str(own.get("origin") or spec.get("origin") or ORIGIN_IMPORT)
    model = str(own.get("model") or (spec.get("model") if origin == ORIGIN_AI else "") or "")
    return {
        "origin": origin,
        **({"model": model} if model else {}),
        **({key: str(own[key]) for key in ("sha256", "source_sha256") if own.get(key)}),
    }


def _field_text(spec: Mapping[str, Any], name: str) -> str | None:
    """A field's text as the document holds it — what a fingerprint is of."""
    if name == "body":
        body = spec["body"]
        if "html" in body:
            return str(body["html"])
        return json.dumps(body["blocks"], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    value = spec.get(name)
    return None if value is None else str(value)


def _plan_origins(version: _Version, source: _Version | None) -> dict[str, dict[str, Any]]:
    """Every field's origin for the ledger, with the document's fingerprints
    kept verbatim, and a translated field marked stale when the source text
    it was made from is not the source text the document holds."""
    spec = version.spec
    names = [
        *TEXT_FIELDS,
        *(name for name in (spec.get("fields") or {}) if name not in TEXT_FIELDS),
    ]
    found: dict[str, dict[str, Any]] = {}
    for name in names:
        facts: dict[str, Any] = _field_facts(spec, name)
        made_from = facts.get("source_sha256")
        if made_from and source is not None and source is not version:
            declared = ((source.spec.get("fields") or {}).get(name) or {}).get("sha256")
            text = _field_text(source.spec, name) if name in TEXT_FIELDS else None
            expected = str(declared) if declared else (text_fingerprint(text) if text else "")
            if not expected:
                version.line.note(
                    INFO,
                    "source_unknown",
                    f"{name}: the source version gives no text or fingerprint to compare with.",
                )
            elif expected != made_from:
                facts["stale"] = True
                version.line.note(
                    WARNING,
                    "translation_stale",
                    f"{name}: translated from an older {source.locale} text than the document "
                    "holds now — to be translated again.",
                )
        found[name] = facts
    return found


def _picture(plan: _Plan, version: _Version, file: str) -> _Picture | None:
    """A picture of the document, read once: where it is, what it is, and the
    asset it is — or will be — in this company's library."""
    sha = plan.files.get(file)
    if sha is not None:
        return plan.pictures[sha]
    relative = Path(file)
    path = (plan.base / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(plan.base):
        version.line.refuse(
            "picture_outside",
            f"„{file}”: pictures are named by a path under the document's directory.",
        )
        return None
    try:
        content = path.read_bytes()
    except OSError:
        version.line.refuse("picture_missing", f"„{file}”: no such file beside the document.")
        return None
    content_type = next((kind for magic, kind in _MAGIC if content.startswith(magic)), "")
    if not content_type and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        content_type = "image/webp"
    if not content_type:
        version.line.refuse(
            "picture_unsupported", f"„{file}” is not a JPEG, a PNG or a WebP picture."
        )
        return None
    if len(content) > settings.MEDIA_MAX_UPLOAD_BYTES:
        version.line.refuse(
            "picture_too_large",
            f"„{file}” has {len(content) / 1024 / 1024:.1f} MB; the library takes "
            f"{settings.MEDIA_MAX_UPLOAD_BYTES / 1024 / 1024:.0f} MB.",
        )
        return None
    sha = hashlib.sha256(content).hexdigest()
    plan.files[file] = sha
    if sha not in plan.pictures:
        plan.pictures[sha] = _Picture(
            sha256=sha,
            path=path,
            content_type=content_type,
            size=len(content),
            asset_id=approved_media_asset_id(
                organization_id=plan.organization_id, source_key=_source_key(sha)
            ),
            known=False,
        )
    return plan.pictures[sha]


def _source_key(sha: str) -> str:
    return f"content-import:{sha}"


def _plan_body(plan: _Plan, version: _Version) -> bool:
    """The version's blocks, with its pictures named as library assets, and
    whether they may be published as they are. False: refused."""
    spec, line = version.spec, version.line
    body = spec["body"]
    assets: dict[str, str] = {}
    alts: dict[str, str] = {}
    pictures = dict(spec.get("images") or {})
    cover = spec.get("cover")
    if cover is not None and "blocks" in body:
        line.refuse("cover_with_blocks", "`cover` goes with an HTML body; blocks name their own.")
        return False
    if cover is not None:
        pictures["import-cover:"] = cover
    for src, given in pictures.items():
        picture = _picture(plan, version, str(given["file"]))
        if picture is None:
            return False
        assets[str(src)] = str(picture.asset_id)
        alts[str(src)] = str(given.get("alt") or "")
        if picture.sha256 not in version.pictures:
            version.pictures.append(picture.sha256)
    if "blocks" in body:
        named: list[str] = []
        blocks = _with_assets(plan, version, body["blocks"], named)
        if version.line.refused:
            return False
        assets.update({asset: asset for asset in named})
        held = False
    else:
        html = str(body["html"])
        if cover is not None:
            html = f'<img src="import-cover:" alt="{_attribute(alts["import-cover:"])}">' + html
        for src, alt in alts.items():
            if alt and src != "import-cover:":
                html = _with_alt(html, src, alt)
        try:
            conversion = convert_html(html, image_assets=assets)
        except HtmlConversionError as error:
            line.refuse("body_unreadable", f"The HTML could not be turned into blocks: {error}")
            return False
        blocks = conversion.blocks
        accepted = {str(kind) for kind in spec.get("accept_losses") or []}
        held = False
        for loss in conversion.losses:
            lost = loss.severity == LOST
            taken = lost and loss.kind in accepted
            if lost and not taken:
                held = True
            line.note(
                WARNING if lost and not taken else INFO,
                f"body_{loss.severity}",
                f"body {loss.severity}: {loss.kind} ×{loss.count}"
                + (f" ({loss.detail})" if loss.detail else "")
                + (f" — e.g. „{loss.sample}”" if loss.sample else "")
                + (" [accepted by the document]" if taken else ""),
            )
    if not blocks:
        line.refuse("body_empty", "The body has no content.")
        return False
    try:
        normalized = [normalize_block(block) for block in blocks]
        for block in normalized:
            validate_site_block(
                block_type=block["block_type"],
                schema_version=block["schema_version"],
                data=block["data"],
            )
        assert_unique_anchors(normalized)
    except (APIException, KeyError, TypeError, ValueError) as error:
        line.refuse("body_invalid", f"The body does not meet the block contracts: {error}")
        return False
    version.blocks = blocks
    version.media_ids = [UUID(asset) for asset in dict.fromkeys(assets.values())]
    if held:
        line.note(
            WARNING,
            "held_for_losses",
            "The converter lost content (above): the version is brought in as a draft and "
            "not published. Fix the HTML, or name the loss in `accept_losses`.",
        )
    return not held


def _with_assets(plan: _Plan, version: _Version, value: Any, named: list[str]) -> Any:
    """Blocks with every `"asset_id": "file:<path>"` replaced by the asset
    that file is in the company's library."""
    if isinstance(value, list):
        return [_with_assets(plan, version, item, named) for item in value]
    if not isinstance(value, dict):
        return value
    found: dict[str, Any] = {}
    for key, item in value.items():
        if key == "asset_id" and isinstance(item, str) and item.startswith("file:"):
            picture = _picture(plan, version, item.removeprefix("file:"))
            if picture is None:
                return value
            if picture.sha256 not in version.pictures:
                version.pictures.append(picture.sha256)
            named.append(str(picture.asset_id))
            found[key] = str(picture.asset_id)
        else:
            found[key] = _with_assets(plan, version, item, named)
    return found


def _attribute(value: str) -> str:
    return (
        value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _with_alt(html: str, src: str, alt: str) -> str:
    """The document's description of a picture, where its `<img>` has none."""

    def give(match: re.Match[str]) -> str:
        tag = match.group(0)
        if re.search(r"\balt\s*=\s*[\"'][^\"']+[\"']", tag):
            return tag
        tag = re.sub(r"\balt\s*=\s*([\"'])\1", "", tag)
        return tag[:4] + f' alt="{_attribute(alt)}"' + tag[4:]

    return re.sub(r"<img\b[^>]*\bsrc\s*=\s*[\"']" + re.escape(src) + r"[\"'][^>]*>", give, html)


def _moment(version: _Version, name: str) -> datetime | None:
    raw = version.spec.get(name)
    if raw is None:
        return None
    try:
        moment = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        moment = None
    if moment is None or moment.tzinfo is None:
        version.line.refuse(
            "date_invalid", f"`{name}` is not a date and time with a zone (ISO 8601): „{raw}”."
        )
        return None
    return moment


def _plan_version(plan: _Plan, version: _Version, source: _Version | None) -> None:
    spec, line, entry, record = version.spec, version.line, version.entry, version.record
    if entry is not None and entry.state == ContentEntryState.REMOVED:
        return
    line.slug = version.slug
    publishable = _plan_body(plan, version)
    if line.refused:
        return
    assert version.blocks is not None
    wants_public = spec["status"] == "published"
    published_at = _moment(version, "published_at")
    changed_at = _moment(version, "changed_at")
    if line.refused:
        return
    if wants_public and published_at is None:
        line.refuse("published_at_missing", "A published version says when it was published.")
        return
    if published_at is not None and published_at > plan.now + CLOCK_SLACK:
        line.refuse(
            "published_at_future",
            f"`published_at` {published_at.isoformat()} is ahead of now. An import publishes "
            "what is published; plan a publication in the panel.",
        )
        return
    if published_at is not None and published_at < EARLIEST_PUBLICATION:
        publishable = False
        line.note(
            WARNING,
            "published_at_implausible",
            f"`published_at` {published_at.date().isoformat()} is plainly not when this was "
            "published. The version is brought in as a draft; give the date to show and run again.",
        )
    if changed_at is None:
        changed_at = published_at
    elif published_at is not None and changed_at < published_at:
        line.note(
            WARNING,
            "changed_before_published",
            "`changed_at` is before `published_at`; the publication date is used for both.",
        )
        changed_at = published_at
    elif changed_at > plan.now + CLOCK_SLACK:
        line.note(WARNING, "changed_at_future", "`changed_at` is ahead of now; now is used.")
        changed_at = plan.now
    version.published_at, version.changed_at = published_at, changed_at

    origins = _plan_origins(version, source)
    version.imported = ImportedText(
        fields={
            key: {
                name: str(value)
                for name, value in origins[field_name].items()
                if name in ("origin", "model", "source_sha256")
            }
            for key, field_name in (
                (IMPORT_TITLE, "title"),
                (IMPORT_EXCERPT, "excerpt"),
                (IMPORT_BODY, "body"),
            )
        },
        ref=f"content-import:{plan.report.source}"[:160],
    )
    metadata = {
        "title": str(spec["title"]).strip(),
        "excerpt": str(spec.get("excerpt") or "").strip(),
        "author_name": str(version.entry_spec.get("author_name") or "").strip(),
        "noindex": bool(spec.get("noindex", False)),
    }
    body_hash = _hash({"blocks": version.blocks})
    term_ids = _wanted_terms(plan, version)
    if line.refused:
        return
    terms_hash = _hash({
        name: sorted(str(item) for item in version.entry_spec.get(name) or [])
        for name in ("categories", "tags")
    })
    written = dict(record.fields) if record is not None else {}

    def was(name: str) -> Any:
        return (written.get(name) or {}).get("written")

    ledger: dict[str, Any] = {name: dict(facts) for name, facts in origins.items()}
    for name, value in metadata.items():
        ledger.setdefault(name, {})["written"] = _hash(value)
    ledger["body"]["written"] = body_hash
    carried = (written.get("terms") or {}).get("ids")
    ledger["terms"] = {"written": terms_hash, **({"ids": carried} if carried is not None else {})}
    kept_slug = entry is not None and not version.change_slug
    ledger["slug"] = {
        "asked": str(spec.get("slug") or ""),
        "written": (was("slug") if kept_slug and was("slug") else version.slug),
    }
    version.ledger = ledger

    if entry is None:
        version.metadata, version.write_body, version.terms = metadata, True, bool(term_ids)
        line.changes = ["text", *(["categories and tags"] if term_ids else [])]
        if version.former:
            line.changes.append(f"{len(version.former)} old address(es)")
    else:
        overwrite = _may_overwrite(plan, version)
        for name, value in metadata.items():
            have = getattr(entry, name)
            if have == value:
                continue
            if was(name) is not None and _hash(have) != was(name) and not overwrite:
                if _hash(value) != was(name):
                    line.note(
                        WARNING,
                        f"{name}_kept",
                        f"`{name}` was changed in the panel after the import; the document's "
                        "newer value is not applied (name the entry in --overwrite-edits to "
                        "replace it).",
                    )
                else:
                    line.note(INFO, f"{name}_kept", f"`{name}` was changed in the panel: kept.")
                ledger[name]["written"] = was(name)
                _kept(line)
                continue
            version.metadata[name] = value
            line.changes.append(name)
        draft = entry.current_draft
        mine = draft is None or (record is not None and record.written_version == draft.number)
        if not mine and not overwrite:
            if body_hash != was("body"):
                line.note(
                    WARNING,
                    "body_kept",
                    "The text was edited in the panel after the import; the document's newer "
                    "text is not applied (name the entry in --overwrite-edits to replace it).",
                )
            else:
                line.note(INFO, "body_kept", "The text was edited in the panel: kept.")
            ledger["body"]["written"] = was("body")
            _kept(line)
        elif body_hash != was("body") or not mine:
            version.write_body = True
            line.changes.append("text")
        now_filed = plan.filed.get(entry.id, set())
        if {str(item) for item in now_filed} != set(term_ids):
            before = written.get("terms") or {}
            if before.get("ids") is not None and sorted(str(i) for i in now_filed) != before["ids"]:
                if not overwrite:
                    line.note(
                        INFO if terms_hash == before.get("written") else WARNING,
                        "terms_kept",
                        "Categories or tags were changed in the panel after the import: kept.",
                    )
                    ledger["terms"] = dict(before)
                    _kept(line)
                else:
                    version.terms = True
            else:
                version.terms = True
            if version.terms:
                line.changes.append("categories and tags")
        if version.change_slug:
            line.changes.append(f"address /{version.slug}/")
        if version.former:
            line.changes.append(f"{len(version.former)} old address(es)")
    _plan_publication(plan, version, wants_public, publishable, was)
    if record is not None and _recorded(version.ledger) != _recorded(record.fields):
        # Nothing of the entry changes, but what the document says about it
        # does — a fingerprint added, an origin corrected.
        version.record_only = not _writes(version)
        if version.record_only:
            line.changes.append("record of origins")
    if line.action == UNCHANGED and (line.changes or version.publish or version.set_published_at):
        line.action = UPDATE
    if line.publication == HELD and line.action in (CREATE, UNCHANGED, UPDATE):
        line.action = HELD


#: What a publication's own transaction writes into the ledger.
_PUBLICATION_FACTS = ("status", "published_at", "changed_at")


def _recorded(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in fields.items() if name not in _PUBLICATION_FACTS}


def _writes(version: _Version) -> bool:
    """Whether the version's own transaction has anything to write."""
    return bool(
        version.entry is None
        or version.metadata
        or version.write_body
        or version.terms
        or version.former
        or version.change_slug
        or version.record_only
    )


def _kept(line: Line) -> None:
    if _WEIGHT[line.action] < _WEIGHT[KEPT]:
        line.action = KEPT


def _wanted_terms(plan: _Plan, version: _Version) -> list[str]:
    """The ids of the terms the entry is filed under — for a term the run is
    about to make, its place in the document."""
    found: list[str] = []
    for kind, name in ((ContentImportKind.CATEGORY, "categories"), (ContentImportKind.TAG, "tags")):
        asked = [str(item) for item in version.entry_spec.get(name) or []]
        if len(asked) > ENTRY_TERMS_MAX:
            version.line.refuse(
                "too_many_terms", f"An entry carries at most {ENTRY_TERMS_MAX} {name}."
            )
            return []
        for external_id in asked:
            term = plan.terms.get((str(kind), external_id))
            if term is None or term.line.refused:
                version.line.refuse(
                    "term_unknown",
                    f"The {name[:-1] if name == 'tags' else 'category'} „{external_id}” is not "
                    "in the document, or is refused.",
                )
                return []
            if kind == ContentImportKind.CATEGORY and term.type_key != version.type_key:
                version.line.refuse(
                    "term_not_of_type",
                    f"The category „{external_id}” belongs to another content type.",
                )
                return []
            found.append(str(term.term_id) if term.term_id else f"{kind}:{external_id}")
    return found


def _plan_publication(
    plan: _Plan,
    version: _Version,
    wants_public: bool,
    publishable: bool,
    was: Callable[[str], Any],
) -> None:
    line, entry, record = version.line, version.entry, version.record
    ledger = version.ledger
    ledger["status"] = {"written": version.spec["status"]}
    ledger["published_at"] = {
        "written": version.published_at.isoformat() if version.published_at else ""
    }
    ledger["changed_at"] = {"written": version.changed_at.isoformat() if version.changed_at else ""}
    if not wants_public:
        line.publication = "draft"
        if entry is not None and entry.state == ContentEntryState.PUBLISHED:
            line.note(
                INFO,
                "not_withdrawn",
                "The document says „draft” and the entry is public: an import takes nothing "
                "off the site. Withdraw it in the panel.",
            )
            line.publication = "published"
        return
    if not publishable:
        line.publication = HELD
        ledger["status"] = {"written": was("status") or "draft"}
        return
    if entry is None:
        version.publish, line.publication = True, "publish"
        return
    draft = entry.current_draft
    mine = version.write_body or (
        draft is not None and record is not None and record.written_version == draft.number
    )
    public = entry.state == ContentEntryState.PUBLISHED and entry.current_publication is not None
    if was("status") == "published" and not public and entry.published_at is not None:
        line.publication = KEPT
        line.note(
            WARNING,
            "withdrawn_in_panel",
            "A person took this entry off the site after the import published it: it stays off.",
        )
        _kept(line)
        return
    touched = any(note.code.endswith("_kept") for note in line.notes)
    if not mine or touched:
        # Something of this version is a person's since the import: what goes
        # in front of readers next is theirs to decide — the import's own
        # updates wait in the draft with it.
        line.publication = "published" if public else KEPT
        if not public:
            line.note(
                WARNING,
                "draft_edited_in_panel",
                "The entry was changed in the panel after the import: publishing it is that "
                "person's to do.",
            )
            _kept(line)
        elif version.write_body or version.metadata or version.terms:
            line.note(
                WARNING,
                "not_republished",
                "The import's updates are saved, but not published: the entry holds a "
                "person's changes, and what goes out next is theirs to decide.",
            )
        return
    if not public:
        version.publish, line.publication = True, "publish"
        return
    assert entry.current_publication is not None and draft is not None
    snapshot = entry.current_publication.snapshot
    stale_date = bool(
        version.changed_at
        and was("changed_at") is not None
        and snapshot.get("changed_at") == was("changed_at")
        and version.changed_at.isoformat() != was("changed_at")
    )
    behind = snapshot.get("version") != draft.number
    if version.write_body or version.metadata or version.terms or stale_date or behind:
        version.publish, line.publication = True, "republish"
    else:
        line.publication = "published"
    if (
        version.published_at is not None
        and entry.published_at is not None
        and entry.published_at != version.published_at
        and was("published_at") == entry.published_at.isoformat()
    ):
        version.set_published_at = True
        line.changes.append("publication date")


# -- the writes ----------------------------------------------------------------


def _retrying[T](plan: _Plan, work: Callable[[], T]) -> T:
    """`work` in one transaction of the tenant; begun again when the database
    stopped it to break a deadlock (a rename of a term crossing a publication
    that carries it, ADR-079 „Uzupełnienie CT2” pkt 24)."""
    for attempt in range(1, DEADLOCK_ATTEMPTS + 1):
        try:
            with _tenant_transaction(plan.organization_id):
                return work()
        except OperationalError as error:
            state = getattr(error.__cause__, "sqlstate", None)
            if state not in _DEADLOCK_STATES or attempt == DEADLOCK_ATTEMPTS:
                raise
            plan.report.retries += 1
            time.sleep(0.2 * attempt)
    raise AssertionError("unreachable")


def _why(error: BaseException) -> str:
    if isinstance(error, APIException):
        detail = error.detail
        codes = error.get_codes()
        return f"{codes}: {detail}" if not isinstance(detail, str) else f"{codes}: {detail}"
    return f"{type(error).__name__}: {error}"


def _apply(plan: _Plan, context: Any) -> None:
    report = plan.report
    started = time.monotonic()
    for key, line in plan.type_lines.items():
        if line.action == CREATE:
            _apply_type(plan, key, line)
    for term in plan.terms.values():
        if not term.line.refused and term.line.action in (CREATE, UPDATE, KEPT):
            _apply_term(plan, term)
    report.timing["types and terms"] = time.monotonic() - started
    scanner_misses = 0
    phases = {"pictures": 0.0, "text": 0.0, "publication": 0.0}
    for entry_spec, versions in plan.entries:
        mark = time.monotonic()
        for version in versions:
            scanner_misses = _apply_pictures(plan, version, scanner_misses)
        phases["pictures"] += time.monotonic() - mark
        mark = time.monotonic()
        # Only what has something to write: a run that changes nothing
        # touches no row, the ledger's included.
        active = [
            version
            for version in versions
            if not version.line.refused and version.blocks and _writes(version)
        ]
        if active:
            try:
                _retrying(plan, partial(_write_entry, plan, entry_spec, active))
            except Exception as error:  # noqa: BLE001 — one entry's failure is the report's
                logger.exception("sites.content_import.entry_failed id=%s", entry_spec["id"])
                for version in active:
                    version.line.refuse("write_failed", _why(error))
        phases["text"] += time.monotonic() - mark
        mark = time.monotonic()
        for version in versions:
            if version.line.refused or not (version.publish or version.set_published_at):
                continue
            try:
                _retrying(plan, partial(_publish, plan, version))
            except Exception as error:  # noqa: BLE001
                logger.exception("sites.content_import.publication_failed id=%s", entry_spec["id"])
                version.line.action = HELD
                version.line.publication = HELD
                version.line.note(
                    REFUSAL,
                    "publication_failed",
                    f"The text is in, as a draft; publishing it failed — {_why(error)}",
                )
        phases["publication"] += time.monotonic() - mark
    report.timing.update(phases)
    versions_done = sum(len(versions) for _spec, versions in plan.entries) or 1
    report.timing["per version"] = sum(phases.values()) / versions_done
    with _tenant_transaction(plan.organization_id):
        record_audit(
            organization=Organization.objects.get(pk=plan.organization_id),
            action=IMPORT_RUN,
            actor=User.objects.get(pk=context.actor_id),
            target_type="site",
            target_id=plan.site.id,
            metadata={
                "source": report.source,
                "document_sha256": report.document_sha256,
                "counts": report.counts(),
                "pictures": report.pictures,
            },
        )


def _apply_type(plan: _Plan, key: str, line: Line) -> None:
    spec = plan.type_specs[key]

    def make() -> ContentCollection:
        collection, _created = create_collection(
            site_id=plan.site.id,
            key=key,
            name=str(spec["name"]),
            kind=str(spec.get("kind", "blog")),
            base_path=str(spec["base_path"]),
            idempotency_key=f"import:{_hash([plan.report.source, key])[:40]}",
            locale_paths={
                locale: path
                for locale, path in (spec.get("locale_paths") or {}).items()
                if locale in plan.locales
            },
            schema_type=str(spec.get("schema_type") or ContentSchemaType.BLOG_POSTING),
        )
        _remember(plan, ContentImportKind.TYPE, key, "", collection.id, {})
        return collection

    try:
        plan.types[key] = _retrying(plan, make)
    except Exception as error:  # noqa: BLE001
        line.refuse("type_refused", _why(error))
        for term in plan.terms.values():
            if term.type_key == key and not term.line.refused:
                term.line.refuse("type_refused", "Its content type could not be made.")
        for _spec, versions in plan.entries:
            for version in versions:
                if version.type_key == key and not version.line.refused:
                    version.line.refuse("type_refused", "Its content type could not be made.")


def _remember(
    plan: _Plan,
    kind: str,
    external_id: str,
    locale: str,
    object_id: UUID,
    fields: Mapping[str, Any],
    *,
    written_version: int | None = None,
) -> ContentImportRecord:
    context = require_tenant_context()
    record, _created = ContentImportRecord.all_objects.update_or_create(
        organization_id=plan.organization_id,
        site=plan.site,
        source=plan.report.source,
        kind=str(kind),
        external_id=external_id,
        locale=locale,
        defaults={
            "object_id": object_id,
            "fields": dict(fields),
            **({"written_version": written_version} if written_version is not None else {}),
        },
        create_defaults={
            "object_id": object_id,
            "fields": dict(fields),
            "written_version": written_version,
            "created_by_id": context.actor_id,
        },
    )
    plan.ledger[str(kind), external_id, locale] = record
    return record


def _apply_term(plan: _Plan, term: _Term) -> None:
    line, spec = term.line, term.spec
    collection = plan.types.get(term.type_key)
    if collection is None:
        line.refuse("type_refused", "Its content type could not be made.")
        return
    kind = KIND_CATEGORIES if term.kind == ContentImportKind.CATEGORY else KIND_TAGS

    def write() -> None:
        if term.create:
            parent = spec.get("parent")
            above = (
                plan.terms[str(ContentImportKind.CATEGORY), str(parent)].term_id
                if parent is not None
                else None
            )
            row, created = create_term(
                collection_id=collection.id,
                kind=kind,
                name=str(spec["names"][plan.default_locale]).strip(),
                parent_id=above,
            )
            term.term_id = row.term.id
            if not created:
                line.note(
                    INFO,
                    "adopted",
                    "A term with this name was there already: the import goes on with it.",
                )
        assert term.term_id is not None
        if term.rename:
            update_term(term_id=term.term_id, collection_id=collection.id, name=term.rename)
        if term.names:
            set_term_names(term_id=term.term_id, collection_id=collection.id, names=term.names)
        for locale, slug in term.slugs.items():
            try:
                with transaction.atomic():
                    change_term_address(
                        term_id=term.term_id,
                        collection_id=collection.id,
                        locale=locale,
                        slug=slug,
                        reason=f"Import treści ({plan.report.source})",
                    )
            except APIException as error:
                line.note(
                    WARNING,
                    "address_refused",
                    f"The address „{slug}” in {locale} was not given: {_why(error)}",
                )
        if term.former:
            _recorded, refused = record_former_term_slugs(term_id=term.term_id, slugs=term.former)
            for slug, why in refused.items():
                line.note(
                    WARNING,
                    "former_slug_refused",
                    f"The old address „{slug}” is left out ({why}).",
                )
        _remember(plan, term.kind, str(spec["id"]), "", term.term_id, term.ledger)

    try:
        _retrying(plan, write)
    except Exception as error:  # noqa: BLE001
        term.term_id = term.record.object_id if term.record is not None else None
        line.refuse("term_refused", _why(error))


def _apply_pictures(plan: _Plan, version: _Version, scanner_misses: int) -> int:
    """Stores the pictures the version needs — each in its own transaction,
    before the entry's: object storage does not roll back with the database,
    and a picture stored once is found again by what it is."""
    if version.line.refused:
        return scanner_misses
    for sha in version.pictures:
        picture = plan.pictures[sha]
        if picture.known:
            continue
        if not picture.failure and scanner_misses >= SCANNER_PATIENCE:
            picture.failure = "the scanner is not answering; pictures wait for the next run"
        if not picture.failure:
            try:
                _retrying(
                    plan,
                    partial(
                        materialize_approved_media_asset,
                        source_key=_source_key(picture.sha256),
                        filename=picture.path.name,
                        content_type=picture.content_type,
                        content=picture.path.read_bytes(),
                    ),
                )
                picture.known = True
                scanner_misses = 0
                plan.report.pictures["uploaded"] += 1
            except Exception as error:  # noqa: BLE001
                unavailable = isinstance(error, MalwareScannerUnavailable) or (
                    isinstance(error, APIException) and "scanner" in str(error.get_codes()).lower()
                )
                scanner_misses = scanner_misses + 1 if unavailable else scanner_misses
                picture.failure = (
                    "the scanner did not answer — run again"
                    if unavailable
                    else f"the library refused it — {_why(error)}"
                )
                plan.report.pictures["failed"] += 1
        if picture.failure:
            version.line.refuse(
                "picture_refused",
                f"„{picture.path.name}”: {picture.failure}. The version is not written: its "
                "text names the picture.",
            )
            return scanner_misses
    return scanner_misses


def _term_ids(plan: _Plan, version: _Version, kind: str, name: str) -> list[UUID]:
    found: list[UUID] = []
    for external_id in version.entry_spec.get(name) or []:
        term = plan.terms[str(kind), str(external_id)]
        if term.term_id is None or term.line.refused:
            raise ValueError(f"The term „{external_id}” could not be made.")
        found.append(term.term_id)
    return found


def _write_entry(plan: _Plan, entry_spec: Mapping[str, Any], versions: Sequence[_Version]) -> None:
    """The text of one document entry, every language version of it, in one
    transaction: all of them or none."""
    context = require_tenant_context()
    external_id = str(entry_spec["id"])
    sibling: ContentEntry | None = next(
        (
            row
            for (kind, found, _locale), record in plan.ledger.items()
            if kind == "entry"
            and found == external_id
            and (row := plan.rows.get(record.object_id)) is not None
            and row.state != ContentEntryState.REMOVED
        ),
        None,
    )
    source_first = sorted(versions, key=lambda item: item.locale != plan.default_locale)
    for version in source_first:
        collection = plan.types[version.type_key]
        assert collection is not None and version.blocks is not None
        entry = version.entry
        key = _hash([plan.report.source, external_id, version.locale])[:40]
        if entry is None:
            title = str(version.metadata["title"])
            if sibling is None:
                entry, _created = create_entry(
                    collection_id=collection.id,
                    slug=version.slug,
                    locale=version.locale,
                    title=title,
                    idempotency_key=f"import:{key}",
                )
            else:
                entry, _created = create_entry_translation(
                    entry_id=sibling.id,
                    locale=version.locale,
                    slug=version.slug,
                    title=title,
                    idempotency_key=f"import:{key}",
                )
            version.entry = entry
            plan.rows[entry.id] = entry
        elif version.change_slug:
            change_entry_slug(
                entry_id=entry.id,
                slug=version.slug,
                reason=f"Import treści ({plan.report.source}): adres z dokumentu",
            )
        sibling = sibling or entry
        changes = {
            name: value for name, value in version.metadata.items() if getattr(entry, name) != value
        }
        if changes:
            update_entry_metadata(entry_id=entry.id, **changes)
        written_version = version.record.written_version if version.record else None
        if version.write_body:
            entry.refresh_from_db(fields=["version"])
            saved, _created = save_entry_draft(
                entry_id=entry.id,
                expected_version=entry.version,
                blocks=version.blocks,
                media_asset_ids=version.media_ids,
                idempotency_key="import:"
                + _hash([key, entry.version, version.ledger["body"]])[:40],
                imported=version.imported,
            )
            written_version = saved.number
        if version.terms or version.record is None:
            categories = _term_ids(plan, version, ContentImportKind.CATEGORY, "categories")
            tags = _term_ids(plan, version, ContentImportKind.TAG, "tags")
            set_entry_categories(entry_id=entry.id, term_ids=categories)
            set_entry_tag_ids(entry_id=entry.id, term_ids=tags)
            version.ledger["terms"] = {
                "written": version.ledger["terms"]["written"],
                "ids": sorted(str(item) for item in (*categories, *tags)),
            }
        if version.former:
            entry.refresh_from_db(fields=["former_slugs", "slug"])
            _recorded, refused = record_former_entry_slugs(context, entry, version.former)
            for slug, why in refused.items():
                version.line.note(
                    WARNING, "former_slug_refused", f"The old address /{slug}/ is left out ({why})."
                )
        # What is public is recorded by the publication's own transaction.
        fields = dict(version.ledger)
        before = version.record.fields if version.record is not None else {}
        for name in _PUBLICATION_FACTS:
            if version.publish or version.set_published_at:
                fields[name] = dict(before.get(name) or {"written": None})
        version.record = _remember(
            plan,
            ContentImportKind.ENTRY,
            external_id,
            version.locale,
            entry.id,
            fields,
            written_version=written_version,
        )


def _publish(plan: _Plan, version: _Version) -> None:
    """One language version goes out — its own transaction, as every other
    publication of one entry is."""
    context = require_tenant_context()
    entry, record = version.entry, version.record
    assert entry is not None and record is not None
    if version.set_published_at:
        row = ContentEntry.all_objects.select_for_update(of=("self",)).get(pk=entry.id)
        before = row.published_at
        row.published_at = version.published_at
        row.save(update_fields=["published_at", "updated_at"])
        record_audit(
            organization=Organization.objects.get(pk=plan.organization_id),
            action=ENTRY_PUBLISHED_AT_SET,
            actor=User.objects.get(pk=context.actor_id),
            target_type="content_entry",
            target_id=entry.id,
            metadata={
                "from": before.isoformat() if before else None,
                "to": version.published_at.isoformat() if version.published_at else None,
                "source": plan.report.source,
            },
        )
    if version.publish:
        publish_entry(
            entry_id=entry.id,
            idempotency_key="import:"
            + _hash([record.written_version, version.ledger["changed_at"], str(timezone.now())])[
                :40
            ],
            published_at=version.published_at,
            changed_at=version.changed_at,
        )
    fields = dict(record.fields)
    for name in ("status", "published_at", "changed_at"):
        fields[name] = version.ledger[name]
    ContentImportRecord.all_objects.filter(pk=record.pk).update(
        fields=fields, updated_at=timezone.now()
    )
    record.fields = fields


__all__ = [
    "CREATE",
    "HELD",
    "KEPT",
    "REFUSED",
    "UNCHANGED",
    "UPDATE",
    "ImportReport",
    "ImportStopped",
    "document_problems",
    "format_report",
    "run_import",
    "text_fingerprint",
]
