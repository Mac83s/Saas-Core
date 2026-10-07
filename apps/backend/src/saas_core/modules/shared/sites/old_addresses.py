"""The map of the addresses a site had before it was built here (ADR-077).

A site that replaces another one inherits its links: every old address either
leads to where that content answers today, or says it is gone for good. The
map is loaded in bulk by an operator (`load_old_addresses`); the resolver asks
it last, after everything the site itself answers, so a live address always
wins over a rule.

How an old address is compared (`address_key`), the same way for the file and
for a visitor's request:

- the query string and the fragment are cut off;
- percent-encoding is undone (`%D0%BF…` and the letters themselves are one
  address), then the text is put in NFC;
- letters are lower-cased, so `/Rasy-Psow/` and `/rasy-psow/` are one address
  (lower-cased, not case-folded: `straße` and `strasse` stay two);
- a trailing slash and doubled slashes do not count.

A language prefix is part of the address like any other segment: `/pl/kontakt`
is a rule of its own, also on a site whose Polish pages have no prefix today.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import set_local_organization_id

from .models import OldAddressOutcome, Site, SiteOldAddress

OLD_ADDRESSES_LOADED = "sites.old_addresses.loaded"
#: What the second column says for an address that is gone for good.
GONE_WORDS = frozenset({"gone", "410"})
#: A protective bound, not a plan limit: one file, one site.
MAX_RULES = 20_000
KEY_MAX_LENGTH = 600
TARGET_MAX_LENGTH = 2048
#: The renderer's proxy lets static files through untouched, so an address
#: with a dot never reaches the site (`apps/frontend/src/proxy.ts`, matcher).
_UNSERVED = re.compile(r"\.")


def address_key(path: str) -> str:
    """One spelling of an old address — see the module's description."""
    value = re.split(r"[?#]", path, maxsplit=1)[0]
    # Until it stops changing: a visitor's path arrives decoded once already,
    # a file may hold it encoded, and both have to end up the same.
    for _ in range(3):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    value = unicodedata.normalize("NFC", unicodedata.normalize("NFC", value).lower())
    return re.sub(r"/{2,}", "/", value).rstrip("/") or "/"


def old_address(*, organization_id: Any, site_id: Any, path: str) -> SiteOldAddress | None:
    """The rule for a visitor's path, read inside the tenant the host named."""
    key = address_key(path)
    if len(key) > KEY_MAX_LENGTH:
        return None
    with transaction.atomic():
        set_local_organization_id(organization_id)
        return SiteOldAddress.all_objects.filter(
            organization_id=organization_id, site_id=site_id, key=key
        ).first()


def site_answers_gone(*, organization_id: Any, site_id: Any) -> bool:
    """Whether any address of the site answers 410 at all."""
    with transaction.atomic():
        set_local_organization_id(organization_id)
        return SiteOldAddress.all_objects.filter(
            organization_id=organization_id, site_id=site_id, outcome=OldAddressOutcome.GONE
        ).exists()


@dataclass(frozen=True, slots=True)
class OldAddressRow:
    line: int
    key: str
    old_path: str
    outcome: str
    to_path: str


@dataclass(slots=True)
class OldAddressReport:
    """What a load does, or would do. `rejected` rows are never written;
    `notes` are true rows worth a look before the switch."""

    rows: list[OldAddressRow] = field(default_factory=list)
    rejected: list[tuple[int, str, str]] = field(default_factory=list)
    notes: dict[str, list[tuple[int, str]]] = field(default_factory=dict)
    added: int = 0
    changed: int = 0
    unchanged: int = 0
    removed: int = 0

    def note(self, kind: str, line: int, text: str) -> None:
        self.notes.setdefault(kind, []).append((line, text))


def read_rows(text: str, *, delimiter: str = ",") -> OldAddressReport:
    """The file's rules, one per old address: `old path,new path` or
    `old path,gone`. A header row, empty lines and `#` comments are skipped;
    a full URL in the first column gives its path."""
    report = OldAddressReport()
    seen: dict[str, OldAddressRow] = {}
    for line, cells in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), start=1):
        cells = [cell.strip() for cell in cells]
        if not any(cells) or cells[0].startswith("#"):
            continue
        if line == 1 and cells[0].lower() in {"old_path", "old", "from", "from_path"}:
            continue
        old = cells[0]
        if len(cells) < 2 or not cells[1]:
            report.rejected.append((line, old, "brak drugiej kolumny: nowy adres albo „gone”"))
            continue
        if re.match(r"https?://", old, re.IGNORECASE):
            old = urlsplit(old).path or "/"
        if not old.startswith("/"):
            report.rejected.append((line, old, "stary adres musi zaczynać się od /"))
            continue
        key = address_key(old)
        if len(key) > KEY_MAX_LENGTH:
            report.rejected.append((line, old, "stary adres jest za długi"))
            continue
        target = cells[1]
        if target.lower() in GONE_WORDS:
            row = OldAddressRow(line, key, old, OldAddressOutcome.GONE, "")
        else:
            reason = _target_refusal(target)
            if reason:
                report.rejected.append((line, old, reason))
                continue
            if address_key(target) == key:
                # The same address in another spelling: the site answers it.
                report.note("same", line, old)
                continue
            row = OldAddressRow(line, key, old, OldAddressOutcome.MOVED, target)
        earlier = seen.get(key)
        if earlier is not None:
            if (earlier.outcome, earlier.to_path) == (row.outcome, row.to_path):
                report.note("repeated", line, old)
            else:
                report.rejected.append((
                    line,
                    old,
                    f"ten sam stary adres co w wierszu {earlier.line}, z innym celem",
                ))
            continue
        seen[key] = row
        report.rows.append(row)
        if _UNSERVED.search(key):
            report.note("unserved", line, old)
    return report


def _target_refusal(target: str) -> str:
    if not target.startswith("/") or target.startswith("//"):
        # Only the site builds addresses: a rule names a path, the site names
        # the host it answers on.
        return "nowy adres to ścieżka na tej stronie (od /) albo „gone”"
    if any(sign in target for sign in ("?", "#", "\\", "\x00", "//")):
        return "nowy adres zawiera niedozwolone znaki (?, #, \\, //)"
    if len(target) > TARGET_MAX_LENGTH:
        return "nowy adres jest za długi"
    return ""


def check_against_site(report: OldAddressReport, *, host: str) -> None:
    """Asks the site what a visitor would get today: an old address that
    still answers (the rule waits behind it), a target that answers nowhere
    (the old address stays a 404 until it does) and a target that itself
    moves (the rule leads straight to where it moves)."""
    from .publication_routing import PublicSiteMoved, PublicSiteNotFound, resolve_public_page

    def answer(path: str) -> str:
        try:
            page = resolve_public_page(host=host, path=path, old_addresses=False)
        except PublicSiteMoved as moved:
            return f"→ {moved.location}"
        except (PublicSiteNotFound, ValidationError):
            # Nothing there, or a path the resolver refuses outright.
            return ""
        return f"→ {page.redirect_url}" if page.redirect_url else "200"

    for row in report.rows:
        # As a visitor's browser would ask: decoded, spelled as in the file.
        live = answer(unquote(re.split(r"[?#]", row.old_path, maxsplit=1)[0]))
        if live:
            report.note("answers_today", row.line, f"{row.old_path} ({live})")
        if row.outcome != OldAddressOutcome.MOVED:
            continue
        target = answer(row.to_path)
        if not target:
            report.note("target_missing", row.line, f"{row.old_path} → {row.to_path}")
        elif target != "200":
            report.note("target_moves", row.line, f"{row.to_path} {target}")


def apply_rows(
    report: OldAddressReport,
    *,
    site: Site,
    actor: User,
    replace: bool,
    dry_run: bool,
    source_hash: str,
) -> None:
    """Writes the file's rules: new ones added, changed ones updated, the rest
    left alone — or removed with `replace`, when the file is the whole map.
    One history row per load; with `dry_run` only the counts are worked out."""
    with transaction.atomic():
        set_local_organization_id(site.organization_id)
        existing = {
            rule.key: rule
            for rule in SiteOldAddress.all_objects.select_for_update().filter(
                organization_id=site.organization_id, site_id=site.id
            )
        }
        create: list[SiteOldAddress] = []
        update: list[SiteOldAddress] = []
        for row in report.rows:
            rule = existing.pop(row.key, None)
            if rule is None:
                create.append(
                    SiteOldAddress(
                        organization_id=site.organization_id,
                        site_id=site.id,
                        key=row.key,
                        old_path=row.old_path,
                        outcome=row.outcome,
                        to_path=row.to_path,
                    )
                )
            elif (rule.outcome, rule.to_path) != (row.outcome, row.to_path):
                rule.outcome, rule.to_path, rule.old_path = row.outcome, row.to_path, row.old_path
                # `bulk_update` does not stamp `auto_now` fields itself.
                rule.updated_at = timezone.now()
                update.append(rule)
            else:
                report.unchanged += 1
        report.added, report.changed = len(create), len(update)
        report.removed = len(existing) if replace else 0
        if dry_run:
            return
        SiteOldAddress.all_objects.bulk_create(create, batch_size=1000)
        SiteOldAddress.all_objects.bulk_update(
            update, ["outcome", "to_path", "old_path", "updated_at"], batch_size=1000
        )
        if replace and existing:
            SiteOldAddress.all_objects.filter(
                organization_id=site.organization_id,
                site_id=site.id,
                pk__in=[rule.pk for rule in existing.values()],
            ).delete()
        record_audit(
            organization=site.organization,
            action=OLD_ADDRESSES_LOADED,
            actor=actor,
            target_type="site",
            target_id=site.id,
            metadata={
                "added": report.added,
                "changed": report.changed,
                "removed": report.removed,
                "unchanged": report.unchanged,
                "rejected": len(report.rejected),
                "replace": replace,
                "source_sha256": source_hash,
            },
        )


def file_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
