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

import copy
import hashlib
import json
import logging
import re
import time
from collections import Counter
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
from rest_framework.exceptions import APIException, ValidationError

from saas_core.content_protocol.provenance import (
    ORIGIN_AI,
    ORIGIN_HUMAN,
    ORIGIN_IMPORT,
    Provenance,
    unit_hash,
)
from saas_core.content_protocol.registry import translation_policy
from saas_core.content_protocol.transliteration import slug_from_title
from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import (
    require_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import decide_feature
from saas_core.modules.shared.media.api import (
    MEDIA_MANAGE,
    STORAGE_ENABLED,
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
    ContentTag,
    Site,
    SiteTextTranslation,
)
from .rich_content import assert_unique_anchors
from .site_texts import shown_texts, term_text_key, term_unit, translation_rows
from .taxonomies import (
    SLUG_PATTERN,
    _archive_answered,
    _assert_sibling_name_free,
    _depth,
    _descendants,
    _find_named,
    _free,
    _source_address,
    _taken,
    change_term_address,
    create_term,
    list_terms,
    record_former_term_slugs,
    set_entry_categories,
    set_entry_tag_ids,
    set_term_names,
    tag_slug,
    update_term,
)
from .term_addresses import (
    CATEGORY_MAX_DEPTH,
    ENTRY_TERMS_MAX,
    KIND_CATEGORIES,
    KIND_TAGS,
    TERM_SLUG_MAX,
    name_slug,
    term_locked,
    term_names,
    term_slug,
)

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
_MARKUP = re.compile(r"</?[A-Za-z][^<>]*>|&(?:[A-Za-z]{2,8}|#\d{1,6}|#x[0-9A-Fa-f]{1,6});")
#: What the converter does to a table that a reader sees, though no word is
#: lost: reported for a look, and the first holds the version back like a
#: loss of content (a table written out as lines of text is no table).
TABLE_LOOK_KINDS = frozenset({"table_too_wide", "table_split"})
HOLDING_KINDS = frozenset({"table_too_wide"})


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
    #: What a person should know before the run that belongs to no one object.
    notices: list[str] = field(default_factory=list)

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
            "notices": list(self.notices),
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
    if report.notices:
        out += ["", "BEFORE YOU RUN:"] + [f"  {notice}" for notice in report.notices]
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
    #: The site held a term of this name that no run of this import made.
    adopted: bool = False
    #: Another term of the document that the site holds as the same one.
    same_as: _Term | None = None
    #: Something of an existing term changes, the ledger's row at least.
    write: bool = False
    #: The term as the run will leave it: its place on the plan's shelf.
    stand: ContentTag | None = None


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
    #: The entry and the ledger's row as the plan found them — what a write
    #: begun again after a deadlock starts from.
    found: tuple[ContentEntry | None, ContentImportRecord | None] = (None, None)
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
    #: The languages each translation group has an entry in, by entry.
    groups: dict[UUID, dict[str, UUID]] = field(default_factory=dict)
    #: Why the media library would take no picture now; empty when it would.
    library_problem: str = ""
    #: Each vocabulary as the run will leave it, term by term in the order the
    #: import writes them — the site's tags under "", a type's categories
    #: under its key. Copies of the site's rows and stand-ins for the terms
    #: the run makes; nothing here is ever saved (`_foresee`).
    shelves: dict[str, list[ContentTag]] = field(default_factory=dict)
    #: Which term of the document stands for a term on a shelf, by its id there.
    stands: dict[Any, _Term] = field(default_factory=dict)
    #: Every term's key on the site: a new key is free among all of them.
    keys: set[str] = field(default_factory=set)
    #: The site's texts in each other language as the run will leave them:
    #: a term's name there is found by the words of its name in the site's
    #: language, so two terms that read the same share it (`site_texts`).
    texts: dict[str, list[SiteTextTranslation]] = field(default_factory=dict)
    #: A content type the site has, to read its tags under.
    any_type: ContentCollection | None = None

    @property
    def default_locale(self) -> str:
        return str(self.site.default_locale)

    def namespace(self, type_key: str, locale: str) -> _Namespace:
        return self.namespaces.setdefault((type_key, locale), _Namespace())


def _where(document: Any, path: Sequence[Any]) -> str:
    """A place in the document as a person finds it: the object's own id and
    language rather than its position in a list."""
    parts = [str(part) for part in path]
    if len(path) < 2 or path[0] not in ("entries", "categories", "tags", "types"):
        return "/".join(parts) or "(document)"
    try:
        item = document[path[0]][path[1]]
        name = item.get("key" if path[0] == "types" else "id", path[1])
        label = f"{path[0]} „{name}”"
        rest = list(path[2:])
        if rest[:1] == ["versions"] and len(rest) > 1:
            label += f" ({item['versions'][rest[1]].get('locale', rest[1])})"
            rest = rest[2:]
    except (AttributeError, IndexError, KeyError, TypeError):
        return "/".join(parts)
    return label + (": " + "/".join(str(part) for part in rest) if rest else "")


def document_problems(document: Any) -> list[str]:
    """What keeps the document from being a `content-import.v1` at all."""
    validator = Draft202012Validator(DOCUMENT_SCHEMA)
    problems = [
        f"{_where(document, list(error.absolute_path))} — {error.message}"
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
    for group, locale, entry_id in ContentEntry.all_objects.filter(
        organization_id=organization.id,
        translation_group__in={row.translation_group for row in plan.rows.values()},
    ).values_list("translation_group", "locale", "id"):
        plan.groups.setdefault(group, {})[str(locale)] = entry_id
    if not context.has_permission(MEDIA_MANAGE):
        plan.library_problem = "the operator's role has no right to add media (`media.manage`)"
    else:
        storage = decide_feature(STORAGE_ENABLED)
        if not storage.allowed:
            plan.library_problem = (
                f"the company's plan gives no media library now ({storage.reason})"
            )
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
    # The site's tags are read under a type it has: the document's first, or
    # any other when the document's are all still to be made.
    plan.any_type = next(
        (row for key, row in plan.types.items() if row is not None),
        min(existing.values(), key=lambda row: str(row.key), default=None),
    )


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


def _markup(text: str) -> str:
    """The first piece of HTML in a text that is shown as typed — a tag or a
    character reference — or nothing. A title, an excerpt or a name holding
    one would show it to readers letter by letter."""
    found = _MARKUP.search(text)
    return found.group(0) if found else ""


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
    if first_type and plan.any_type is not None:
        for found in list_terms(collection_id=plan.any_type.id, kind=KIND_TAGS).terms:
            current["", str(found.term.id)] = found
    for (scope, _id), found in current.items():
        plan.shelves.setdefault(scope, []).append(_stand_in(found.term))
    for locale in plan.locales:
        if locale != plan.default_locale:
            plan.texts[locale] = translation_rows(plan.site, locale)
    plan.keys = set(
        ContentTag.all_objects.filter(
            organization_id=plan.organization_id, site_id=plan.site.id
        ).values_list("slug", flat=True)
    )
    for kind, name in ((ContentImportKind.CATEGORY, "categories"), (ContentImportKind.TAG, "tags")):
        for spec in document.get(name, []):
            type_key = str(spec["type"]) if kind == ContentImportKind.CATEGORY else first_type
            term = _plan_term(plan, str(kind), spec, type_key, current)
            plan.terms[str(kind), str(spec["id"])] = term
            plan.report.lines.append(term.line)
    _names_shared(plan)


def _vocabulary(term: _Term) -> tuple[str, str]:
    """Which terms a term's names are told apart among: the site's tags, or
    one type's categories."""
    return (term.kind, term.type_key if term.kind == ContentImportKind.CATEGORY else "")


def _names_shared(plan: _Plan) -> None:
    """Two different terms of one vocabulary that read the same in a
    language other than the site's: both stay, and the report says which —
    readers would see two archives under one name."""
    seen: dict[tuple[str, str, str, str], _Term] = {}
    for term in plan.terms.values():
        if term.line.refused or term.same_as is not None:
            continue
        for locale, name in term.spec["names"].items():
            if locale == plan.default_locale or locale not in plan.locales:
                continue
            key = (*_vocabulary(term), str(locale), name_slug(str(name)))
            other = seen.setdefault(key, term)
            if other is not term:
                term.line.note(
                    WARNING,
                    "name_shared",
                    f"Its name in {locale}, „{name}”, is also the name of „{other.spec['id']}”: "
                    "two different terms that read the same there. Both are kept; the second "
                    "one's address in that language gets a number.",
                )


def _same_named(plan: _Plan, term: _Term, name: str) -> _Term | None:
    """An earlier term of the document that the site would hold as the same
    one: same vocabulary, same place in the tree, same name in the site's
    language (by its slug — „Porady” and „porady” are one tag)."""
    wanted = name_slug(name)
    for other in plan.terms.values():
        if (
            other is not term
            and not other.line.refused
            and other.same_as is None
            and _vocabulary(other) == _vocabulary(term)
            and other.spec.get("parent") == term.spec.get("parent")
            and name_slug(str(other.spec["names"].get(plan.default_locale, ""))) == wanted
        ):
            return other
    return None


def _stand_in(term: ContentTag) -> ContentTag:
    """A copy of a term's row for the plan's shelf. It is never saved: the
    plan changes it the way the import will change the row."""
    stand = copy.copy(term)
    stand.locale_slugs = dict(term.locale_slugs or {})
    stand.former_slugs = list(term.former_slugs or [])
    stand.slug_locked_at = dict(term.slug_locked_at or {})
    return stand


def _scope(term: _Term) -> str:
    return term.type_key if term.kind == ContentImportKind.CATEGORY else ""


def _above(plan: _Plan, term: _Term) -> ContentTag | None:
    """The category a category of the document hangs under, on the shelf."""
    parent = term.spec.get("parent")
    if parent is None:
        return None
    return _standing_for(plan.terms[str(ContentImportKind.CATEGORY), str(parent)]).stand


def _name_beside(
    name: str, above: ContentTag | None, shelf: Sequence[ContentTag], stand: ContentTag | None
) -> bool:
    """Whether another term beside this one reads the same — what makes the
    service refuse a new category and any rename (`term_name_taken`)."""
    try:
        _assert_sibling_name_free(name, above, shelf, stand)
    except ValidationError:
        return True
    return False


def _met(plan: _Plan, term: _Term, name: str) -> ContentTag | None:
    """The term `create_term` will answer with instead of making one, as the
    vocabulary will stand when the import reaches this term: a tag the name
    means — by its key or its address in any language — or a category of
    that name in the same place of the tree. It may be a row the site holds
    or a term this very run makes earlier. Refuses the line where the
    service will refuse to make the term."""
    shelf = plan.shelves.setdefault(_scope(term), [])
    if term.kind == ContentImportKind.TAG:
        return _find_named(name, sorted(shelf, key=lambda other: (other.position, other.slug)))
    above = _above(plan, term)
    if above is not None and _depth(above, {other.pk: other for other in shelf}) >= (
        CATEGORY_MAX_DEPTH
    ):
        term.line.refuse(
            "term_too_deep",
            f"Categories nest {CATEGORY_MAX_DEPTH} deep at most; this one would hang deeper.",
        )
        return None
    place = above.pk if above is not None else None
    same = next((other for other in shelf if other.parent_id == place and other.name == name), None)
    if same is None and _name_beside(name, above, shelf, None):
        term.line.refuse(
            "term_name_taken",
            f"A category beside it reads the same as „{name}” (another spelling of the "
            "name): the site takes one of them. Give this one the other's exact name, or "
            "another name.",
        )
    return same


def _made(plan: _Plan, term: _Term, name: str) -> ContentTag:
    """The stand-in of a term the run makes: its key and its address in the
    site's language, as `create_term` will make them."""
    shelf = plan.shelves.setdefault(_scope(term), [])
    above = _above(plan, term)
    place = above.pk if above is not None else None
    natural = (tag_slug(name) if term.kind == ContentImportKind.TAG else "") or name_slug(name)
    taken = _taken(shelf, None)
    key = _free(natural, plan.keys | taken)
    address = _free(natural, taken)
    stand = ContentTag(
        # After every row the site holds and in the order the run makes
        # them, as the rows' own ids will be (`_settle` goes by id).
        id=UUID(int=(1 << 128) - (1 << 64) + len(plan.stands)),
        organization_id=plan.organization_id,
        site_id=plan.site.id,
        parent_id=place,
        slug=key,
        name=name,
        locale_slugs={plan.default_locale: address} if address != key else {},
        former_slugs=[],
        slug_locked_at={},
        position=1 + max((item.position for item in shelf if item.parent_id == place), default=-1),
    )
    plan.keys.add(key)
    shelf.append(stand)
    return stand


def _say(plan: _Plan, stand: ContentTag, locale: str, name: str) -> None:
    """A term's name in another language, written where `set_term_names`
    writes it: in the site's text for the words of the term's own name —
    one row for every term that reads the same."""
    unit, rows = term_unit(stand), plan.texts[locale]
    row = next((item for item in rows if item.source_hash == unit.source_hash), None)
    if row is None:
        row = SiteTextTranslation(
            organization_id=plan.organization_id,
            site=plan.site,
            locale=locale,
            source_hash=unit.source_hash,
            source_text=unit.text,
        )
    else:
        rows.remove(row)
    row.anchor, row.text = unit.key, name
    row.provenance = (
        Provenance(
            origin=ORIGIN_HUMAN,
            source_hash=unit.source_hash,
            written_hash=unit_hash(unit.kind, name),
            model="",
            at=plan.now.isoformat(),
        ).as_dict()
        if name
        else None
    )
    # The latest write is the one read last.
    rows.append(row)


def _settle(plan: _Plan, locale: str) -> None:
    """What `settle_term_addresses` does after every write of a name in a
    language: each term whose address there is still open takes it from the
    name visitors read — the first free one — and a term without a name there
    answers under the site's language's address again. Every open term, not
    only the one just named: a term that reads the same shares the name, and
    an address freed a moment ago is taken by whoever waited for it with a
    number."""
    if locale == plan.default_locale:
        return
    stands = sorted(
        ((stand, scope) for scope, shelf in plan.shelves.items() for stand in shelf),
        key=lambda found: found[0].pk,
    )
    shown = shown_texts([term_unit(stand) for stand, _scope in stands], plan.texts[locale])
    held = {
        scope: Counter(name for other in shelf for name in term_names(other))
        for scope, shelf in plan.shelves.items()
    }
    for stand, scope in stands:
        if term_locked(stand, locale):
            continue
        wanted = name_slug(shown.get(term_text_key(stand.pk), ""))
        have = stand.locale_slugs.get(locale)
        if wanted == (have or "") and held[scope][wanted] <= 1:
            continue
        held[scope].subtract(term_names(stand))
        if wanted:
            stand.locale_slugs[locale] = _free(wanted, _taken(plan.shelves[scope], stand))
        else:
            stand.locale_slugs.pop(locale, None)
        held[scope].update(term_names(stand))


def _foresee(plan: _Plan, term: _Term, *, made: bool) -> None:
    """Carries what the plan decided for a term over to its stand-in, in the
    order the import writes it and by the rules its services follow, so that
    the next term of the document meets the vocabulary this one leaves — and
    says now what a service would say then. A name another term beside it
    reads as refuses the term (nothing of it is written); an address or a
    former address that leads to another term is left out, and said."""
    stand, line, default = term.stand, term.line, plan.default_locale
    assert stand is not None
    shelf = plan.shelves[_scope(term)]
    if term.rename:
        above = next((other for other in shelf if other.pk == stand.parent_id), None)
        if _name_beside(term.rename, above, shelf, stand):
            line.refuse(
                "term_name_taken",
                f"Another term beside it reads the same as „{term.rename}”: the site does not "
                "take the new name, and nothing of this term is written.",
            )
            return
        stand.name = term.rename
        if not term_locked(stand, default):
            stand.locale_slugs = _source_address(stand, term.rename, shelf, default)
        for locale in plan.locales:
            _settle(plan, locale)
    for locale, name in term.names.items():
        _say(plan, stand, locale, name)
        _settle(plan, locale)
    for locale, slug in list(term.slugs.items()):
        others = [other for other in shelf if other.pk != stand.pk]
        holder = next(
            (
                other
                for other in others
                if slug == other.slug or slug in (other.locale_slugs or {}).values()
            ),
            None,
        )
        redirects = next((other for other in others if slug in (other.former_slugs or [])), None)
        refusal = ""
        if holder is not None:
            refusal = f"„{holder.name}” has it."
        elif redirects is not None:
            refusal = (
                f"it redirects to „{redirects.name}” today — a person takes such an address "
                "over in the panel."
            )
        if refusal:
            line.note(
                WARNING,
                "address_refused",
                f"The address „{slug}” in {locale} is not given: {refusal}",
            )
            del term.slugs[locale]
            continue
        before = {
            code: term_slug(stand, default_locale=default, locale=code) for code in plan.locales
        }
        stand.locale_slugs[locale] = slug
        stand.slug_locked_at.setdefault(locale, "import")
        if not made:
            # An address that answered a visitor keeps leading to the term.
            under = _descendants(stand, shelf)
            left = [
                before[code]
                for code in plan.locales
                if term_slug(stand, default_locale=default, locale=code) != before[code]
                and _archive_answered(plan.site, stand, code, under)
            ]
            current = {stand.slug, *stand.locale_slugs.values()}
            stand.former_slugs = list(
                dict.fromkeys(item for item in [*stand.former_slugs, *left] if item not in current)
            )
    own, elsewhere = term_names(stand), _taken(shelf, stand)
    recorded: list[str] = []
    for raw in term.former:
        slug = raw.strip().lower()
        if not slug or slug in own or slug in recorded:
            continue
        if not SLUG_PATTERN.fullmatch(slug) or len(slug) > TERM_SLUG_MAX:
            why = f"an address has at most {TERM_SLUG_MAX} letters, digits and single hyphens"
        elif slug in elsewhere:
            why = "it leads to another term of the vocabulary"
        else:
            recorded.append(slug)
            continue
        line.note(WARNING, "former_slug_refused", f"The old address „{slug}” is left out: {why}.")
    term.former = recorded
    stand.former_slugs = [*stand.former_slugs, *recorded]


def _plan_term(
    plan: _Plan,
    kind: str,
    spec: Mapping[str, Any],
    type_key: str,
    current: Mapping[tuple[str, str], Any],
) -> _Term:
    # As the services keep a name: trimmed, one space between its words.
    names = {str(locale): " ".join(str(name).split()) for locale, name in spec["names"].items()}
    default = plan.default_locale
    line = Line(kind=kind, external_id=str(spec["id"]), label=names.get(default, ""))
    term = _Term(line=line, spec=spec, kind=kind, type_key=type_key)
    if default not in names:
        line.refuse("name_missing", f"No name in the site's language ({default}).")
        return term
    for locale, name in names.items():
        if _markup(name):
            line.refuse(
                "markup_in_name",
                f"Its name in {locale} holds HTML („{_markup(name)}”); a name is shown as typed.",
            )
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
    for locale, name in names.items():
        if (name or locale == default) and not name_slug(name):
            line.refuse(
                "name_invalid",
                f"Its name in {locale}, „{name}”, has no letter or digit: the site takes no "
                "such name, and nothing of this term is written.",
            )
            return term
    term.ledger = {
        "names": {locale: _hash(name) for locale, name in names.items()},
        "slugs": dict(wanted_slugs),
        # What the document says of the term that the core has no field for
        # (a description, say), kept as given.
        "extra": dict(spec.get("fields") or {}),
    }
    if found is None:
        twin = _same_named(plan, term, names[default])
        if twin is not None:
            term.same_as = twin
            term.term_id = twin.term_id
            line.note(
                WARNING,
                "term_merged",
                f"In {default} it has the name of „{twin.spec['id']}” („{names[default]}”): the "
                "site holds one term for both. This id stands for that term; its own names in "
                "other languages and its addresses are not applied.",
            )
            return term
        if record is not None:
            line.note(
                WARNING,
                "made_again",
                "An earlier run made this term and it is no longer in the site (somebody "
                "deleted it): it is made again.",
            )
        met = _met(plan, term, names[default])
        if line.refused:
            return term
        held = plan.stands.get(met.pk) if met is not None else None
        if met is not None and held is not None:
            # A term another id of the document stands for — one this run
            # makes a moment earlier, or one an earlier run made for that id.
            term.same_as, term.term_id = held, held.term_id
            line.note(
                WARNING,
                "term_merged",
                f"Its name, „{names[default]}”, leads to „{held.spec['id']}” („{met.name}”) — "
                "it is that term's key or its address in one of the site's languages: the "
                "site holds one term for both. This id stands for that term; its own names "
                "and its addresses are not applied.",
            )
            return term
        if met is None:
            term.create = True
            term.names = {locale: name for locale, name in names.items() if locale != default}
            term.slugs = wanted_slugs
            term.former = [str(slug) for slug in spec.get("former_slugs") or []]
            stand = _made(plan, term, names[default])
            term.stand, plan.stands[stand.pk] = stand, term
            _foresee(plan, term, made=True)
            line.action = CREATE
            line.changes = [f"names in {', '.join(sorted(names))}"]
            return term
        found = current[_scope(term), str(met.pk)]
        term.adopted, record = True, None
    term.term_id, term.record = found.term.id, record
    stand = next(other for other in plan.shelves[_scope(term)] if other.pk == found.term.id)
    term.stand = stand
    fields = record.fields if record is not None else {}
    written = fields.get("names") or {}
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
                f"The name in {locale} is „{have}” in the site — a person's; the document's "
                f"„{name}” is not applied.",
            )
            term.ledger["names"][locale] = written.get(locale, "")
        elif locale == default:
            term.rename = name
        else:
            term.names[locale] = name
    asked = fields.get("slugs") or {}
    for locale, slug in wanted_slugs.items():
        have = str(found.slugs.get(locale, ""))
        if have == slug:
            continue
        if term.adopted or asked.get(locale) == slug or (locale in asked and have != asked[locale]):
            # A term the import did not make, or an address asked for once
            # that is something else today: a person's address (or one the
            # vocabulary could not give). It stays.
            line.note(
                WARNING if term.adopted else INFO,
                "address_kept",
                f"The address in {locale} stays „{have}” (the document asks for „{slug}”).",
            )
            continue
        term.slugs[locale] = slug
    have_former = {str(item) for item in found.term.former_slugs or []}
    term.former = [
        str(slug) for slug in spec.get("former_slugs") or [] if str(slug) not in have_former
    ]
    _foresee(plan, term, made=False)
    if line.refused:
        return term
    plan.stands.setdefault(stand.pk, term)
    extra_changed = record is not None and (fields.get("extra") or {}) != term.ledger["extra"]
    line.changes = [
        *(["name"] if term.rename else []),
        *(f"name in {locale}" for locale in sorted(term.names)),
        *(f"address in {locale}" for locale in sorted(term.slugs)),
        *(["former addresses"] if term.former else []),
        *(["record of other fields"] if extra_changed else []),
    ]
    if term.adopted:
        line.note(
            WARNING,
            "term_adopted",
            "A term of this name is in the site already and no run of this import made it. "
            "The run goes on with it instead of making one, and changes this of it: "
            + (", ".join(line.changes) or "nothing")
            + ". Its other names and its addresses stay as they are.",
        )
        line.changes = ["adopted", *line.changes]
    if line.changes and line.action != KEPT:
        line.action = UPDATE
    term.write = bool(line.changes)
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
        _wait_for_source(source, versions)
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
    if plan.library_problem:
        # Said by the plan, not left for the run to find at every picture.
        for entry_spec, versions in plan.entries:
            for version in versions:
                if not version.line.refused and any(
                    not plan.pictures[sha].known for sha in version.pictures
                ):
                    version.line.refuse(
                        "library_unavailable",
                        f"Its pictures cannot be stored: {plan.library_problem}.",
                    )
            _wait_for_source(_source_version(plan, entry_spec, versions), versions)
    _notice_translations(plan)


def _wait_for_source(source: _Version | None, versions: Sequence[_Version]) -> None:
    """Translations come in with their source, not before it: where the
    source version is not in the site yet and is refused, the entry's other
    new versions wait for the run that brings it. (Published alone, one of
    them would stand as the original — to readers, and to a translation
    engine that fills in the languages an original lacks.)"""
    if source is None or not source.line.refused or source.entry is not None:
        return
    for version in versions:
        if version is not source and not version.line.refused and version.entry is None:
            version.line.refuse(
                "source_refused",
                f"Its source version ({source.locale}) is refused: the translations come in "
                "together with it.",
            )


def _notice_translations(plan: _Plan) -> None:
    """Publishing an original tells the translation engine. Whether the
    company lets it translate changes by itself is the engine's own setting,
    which this module does not read — so the plan says what could follow."""
    if translation_policy(organization_id=plan.organization_id).mode == "off":
        return
    lacking: dict[str, int] = {}
    for entry_spec, versions in plan.entries:
        source = _source_version(plan, entry_spec, versions) or next(iter(versions), None)
        if source is None or not source.publish:
            continue
        have = {version.locale for version in versions if not version.line.refused}
        if source.entry is not None:
            have |= set(plan.groups.get(source.entry.translation_group, {}))
        for locale in plan.locales:
            if locale not in have:
                lacking[locale] = lacking.get(locale, 0) + 1
    if lacking:
        plan.report.notices.append(
            "The translation engine is on for this company. If it also translates changes by "
            "itself („Tłumaczenia” → automatic translation), publishing these originals orders "
            "machine translations — paid in credits — into the languages the document lacks: "
            + ", ".join(f"{locale} ×{count}" for locale, count in sorted(lacking.items()))
            + ". Check that setting before --apply."
        )


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
        version.found = (row, record)
        line.action, line.slug = UNCHANGED, str(row.slug)
    elif record is not None:
        line.note(
            WARNING,
            "made_again",
            "An earlier run made this version and it is no longer in the site (erased with "
            "its content type): it is made again, and published if the document says so.",
        )
    for name in ("title", "excerpt"):
        found = _markup(str(spec.get(name) or ""))
        if found and not line.refused:
            line.refuse(
                f"markup_in_{name}",
                f"The {name} holds HTML („{found}”). A {name} is shown as typed — on a card, "
                "in a search result — so the markup would be read out letter by letter. Give "
                "plain text.",
            )
    if line.refused:
        pass
    elif plan.type_lines[type_key].refused:
        line.refuse("type_refused", "Its content type is refused (see the type's line).")
    elif locale not in plan.locales:
        line.refuse(
            "locale_not_enabled",
            f"The site has no language „{locale}”. Switch it on in the panel, then run again.",
        )
    elif row is None and _foreign_version(plan, entry_spec, locale):
        line.refuse(
            "version_exists",
            f"The entry already has a version in „{locale}” that this import did not make — "
            "a person's or a translation job's. Remove that version in the panel, or leave "
            "this one out of the document.",
        )
    elif row is not None and row.state == ContentEntryState.REMOVED:
        line.action = KEPT
        line.note(
            WARNING,
            "removed_in_panel",
            "A person removed this entry in the panel after an earlier run; it is not made again.",
        )
    return version


def _foreign_version(plan: _Plan, entry_spec: Mapping[str, Any], locale: str) -> bool:
    """Whether the entry's translation group holds an entry in `locale` that
    no run of this import made."""
    for (kind, external_id, _locale), record in plan.ledger.items():
        row = plan.rows.get(record.object_id) if kind == "entry" else None
        if row is None or external_id != str(entry_spec["id"]):
            continue
        if row.state != ContentEntryState.REMOVED:
            return locale in plan.groups.get(row.translation_group, {})
    return False


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
        # A field the core has no place for yet (an SEO title, say) is kept
        # with its words, so it can be filled in from here one day.
        **({"text": str(own["text"])} if name not in TEXT_FIELDS and "text" in own else {}),
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
            lost = loss.severity == LOST or loss.kind in HOLDING_KINDS
            taken = lost and loss.kind in accepted
            if lost and not taken:
                held = True
            look = (lost and not taken) or loss.kind in TABLE_LOOK_KINDS
            line.note(
                WARNING if look else INFO,
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
            "The converter lost content, or wrote a table out as lines of text (above): the "
            "version is brought in as a draft and not published. Fix the HTML, or name the "
            "loss in `accept_losses`.",
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
        # Not „now”: that would be another moment at every run, and every run
        # would publish the entry again.
        line.note(
            WARNING,
            "changed_at_future",
            "`changed_at` is ahead of now; the publication date is used instead.",
        )
        changed_at = published_at
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
            # A field without words says nothing about who wrote the text.
            if field_name != "excerpt" or str(spec.get("excerpt") or "").strip()
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
            held = _standing_for(term)
            mark = str(held.term_id) if held.term_id else f"{kind}:{held.spec['id']}"
            if mark not in found:
                found.append(mark)
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
    if not public and entry.published_at is not None:
        # It was out and is off. The import never withdraws, so that is a
        # person's act — whoever published it, the import or they themselves.
        line.publication = KEPT
        line.note(
            WARNING,
            "withdrawn_in_panel",
            "This entry was public and a person took it off the site: it stays off.",
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
        if not term.line.refused and term.same_as is None and (term.create or term.write):
            _apply_term(plan, term)
    report.timing["types and terms"] = time.monotonic() - started
    scanner_misses = 0
    phases = {"pictures": 0.0, "text": 0.0, "publication": 0.0}
    for entry_spec, versions in plan.entries:
        mark = time.monotonic()
        for version in versions:
            scanner_misses = _apply_pictures(plan, version, scanner_misses)
        _wait_for_source(_source_version(plan, entry_spec, versions), versions)
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
                    version.entry, version.record = version.found
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
                _standing_for(plan.terms[str(ContentImportKind.CATEGORY), str(parent)]).term_id
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
                    WARNING,
                    "term_adopted",
                    "A term of this name appeared in the site while the import ran: the run "
                    "goes on with it instead of making one.",
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


def _standing_for(term: _Term) -> _Term:
    """The term of the document that the site holds for this one: itself, or
    the earlier term of the same name it was merged with."""
    return term.same_as if term.same_as is not None else term


def _term_ids(plan: _Plan, version: _Version, kind: str, name: str) -> list[UUID]:
    found: list[UUID] = []
    for external_id in version.entry_spec.get(name) or []:
        term = _standing_for(plan.terms[str(kind), str(external_id)])
        if term.term_id is None or term.line.refused:
            raise ValueError(f"The term „{external_id}” could not be made.")
        if term.term_id not in found:
            found.append(term.term_id)
    return found


def _write_entry(plan: _Plan, entry_spec: Mapping[str, Any], versions: Sequence[_Version]) -> None:
    """The text of one document entry, every language version of it, in one
    transaction: all of them or none."""
    context = require_tenant_context()
    external_id = str(entry_spec["id"])
    for version in versions:
        # Begun again after a deadlock: nothing of the attempt the database
        # took back is left in hand.
        version.entry, version.record = version.found
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
    # The source version first: the oldest entry of a group that has none in
    # the site's language is what a translation engine takes for the original.
    source_locale = str(entry_spec.get("source_locale") or plan.default_locale)
    source_first = sorted(
        versions,
        key=lambda item: (item.locale != source_locale, item.locale != plan.default_locale),
    )
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
