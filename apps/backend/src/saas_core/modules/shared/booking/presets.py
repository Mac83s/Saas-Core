"""Booking presets: what a company starts an offer from (ADR-072 §10).

A preset is data in `packages/contracts/booking-presets/`, not code: the
manifest names them in the order a company sees them, each version is a file
that never changes once published. This module reads them — the image carries
a copy (`BOOKING_PRESET_CONTRACTS_PATH`, system check `booking.E010`) — and
answers which ones a company may choose from.

Applying one is a copy, not a reference: `apply_preset` makes an inactive
offer that remembers where it came from and is the company's own from then on.
Only a `ready` preset applies, and a ready one uses nothing the engine cannot
do (the contract's test keeps that), so the copy needs no checks of its own.

A preset that is not ready is announced („wkrótce”): a company signs up to be
told when it is, and may say what it lacks (`save_interest`, owner's answer
14 a+b) — the platform's list of what to build next.

Ready does not always mean bookable through the site (owner decision 67a): a
preset whose `online_booking` is `soon` — today a visit at the customer's —
makes an offer the team books in the panel, hidden from the public form until
a later version of the preset says otherwise. Stays, rentals and care stays
said so until the public form took offers booked from–to (phase 5b, their
version 3).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Any, NoReturn
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .item_translations import source_locale
from .models import PaymentPolicy, PresetInterest, Service
from .services import BOOKING_ENABLED, BOOKING_MANAGE
from .setup import Saved, ServiceSetup, _manage, _saved_service, _write_service, setup_write

READY = "ready"
#: How much a company may write under „Czego Ci brakuje?”.
INTEREST_NOTE_MAX = 1000


@dataclass(frozen=True, slots=True)
class Preset:
    id: str
    version: int
    #: `ready`: core takes such bookings now; `soon`: shown, not yet appliable.
    readiness: str
    #: {pl|en: {name, description}}
    labels: dict[str, dict[str, str]]
    time_model: str
    #: What a booking takes: `staff`, `unit`, `unit_group` or `seat`.
    booked_subject: str
    #: Whether a person does it: `required`, `optional` or `none`.
    booked_staff: str
    place: str
    required_inputs: tuple[str, ...]
    catalog_category: str | None
    #: The page template it suggests for the company's site, or None.
    page_template: str | None
    #: Whether a customer books it through the site: `ready`, or `soon` — the
    #: team books in the panel (`soon` too for a preset that is not ready).
    online_booking: str
    #: The whole file, for `apply_preset`.
    raw: dict[str, Any]


def _directory() -> Path:
    return Path(settings.BOOKING_PRESET_CONTRACTS_PATH)


@lru_cache(maxsize=1)
def _catalogue() -> tuple[tuple[str, dict[int, Preset]], ...]:
    """Every preset by id, in the manifest's order, with all its versions.

    Raises `ImproperlyConfigured` when a file is missing or unreadable — the
    system check calls this at start, so a deploy fails instead of a click."""
    directory = _directory()
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        return tuple(
            (
                entry["id"],
                {
                    int(version): _preset(json.loads((directory / name).read_text("utf-8")))
                    for version, name in entry["versions"].items()
                },
            )
            for entry in manifest["presets"]
        )
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ImproperlyConfigured(
            f"Presety rezerwacji w {directory} są nieczytelne: {error}"
        ) from error


def _preset(raw: dict[str, Any]) -> Preset:
    return Preset(
        id=raw["id"],
        version=int(raw["version"]),
        readiness=raw["readiness"],
        labels={
            locale: {"name": texts["name"], "description": texts["description"]}
            for locale, texts in raw["labels"].items()
        },
        time_model=raw["timeModel"],
        booked_subject=raw["booked"]["subject"],
        booked_staff=raw["booked"]["staff"],
        place=raw["place"],
        required_inputs=tuple(raw.get("requiredInputs", ())),
        catalog_category=raw.get("catalogCategory"),
        page_template=raw.get("pageTemplate"),
        online_booking=raw.get("onlineBooking", raw["readiness"]),
        raw=raw,
    )


def latest_presets() -> list[Preset]:
    """Each preset in its latest version, in the order a company sees them."""
    return [versions[max(versions)] for _id, versions in _catalogue()]


def list_presets() -> list[Preset]:
    """What this company may start an offer from.

    Core's presets today; a product's own (profile, `organizationTypes[]`) join
    them with phase 5. The answer is the only list a caller may choose from —
    the panel, the site and the assistant never read the files themselves.
    """
    # For whoever sets services up; a read, so it works on a lapsed plan too.
    authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED, operation=FeatureOperation.READ)
    return latest_presets()


def find_preset(preset_id: str, version: int | None) -> Preset:
    """The preset a caller named, or a field error on `preset_id` with a code
    the assistant can act on: `preset_unknown`, `preset_not_ready`."""
    versions = dict(_catalogue()).get(preset_id)
    preset = versions.get(version if version is not None else max(versions)) if versions else None
    if preset is None:
        _refuse("Nie ma takiego wzorca.", "preset_unknown")
    if preset.readiness != READY:
        _refuse("Ten wzorzec będzie dostępny wkrótce.", "preset_not_ready")
    return preset


def _refuse(message: str, code: str) -> NoReturn:
    raise ValidationError({"preset_id": [ErrorDetail(message, code=code)]})


def _local(value: str | None) -> time | None:
    return time.fromisoformat(value) if value else None


#: The policies a preset sets by itself: the ones that ask nothing of the
#: company's plan or account.
_PLAIN_POLICIES = (PaymentPolicy.NONE.value, PaymentPolicy.ON_SITE.value)
#: A preset's terms of a prepayment as the offer's fields.
_PAYMENT_TERMS = {
    "deposit_percent": "depositPercent",
    "transfer_due_days": "transferDueDays",
    "balance_due_days_before": "balanceDueDaysBefore",
}


def _refund_terms(preset: Preset) -> dict[str, Any]:
    """A preset's refund thresholds as the offer's fields; nothing where the
    preset says nothing of giving a booking up."""
    terms = preset.raw.get("cancellation")
    if not terms:
        return {}
    return {
        "cancellation_applies_to": terms["appliesTo"],
        "cancellation_refunds": [
            {"min_days_before": row["minDaysBefore"], "refund_percent": row["refundPercent"]}
            for row in terms["refunds"]
        ],
    }


def apply_preset(
    *,
    preset_id: str,
    version: int | None = None,
    name: str,
    duration_minutes: int | None = None,
    staff_ids: list[UUID] | None = None,
    location_ids: list[UUID] | None = None,
    idempotency_key: str = "",
    preview: bool = False,
) -> Saved[ServiceSetup]:
    """Starts an offer from a preset: a copy, switched off, that remembers where
    it came from (ADR-072 §10) — a setup write like `save_service` (§11).

    Only the offer is made. Nobody and no place are picked for the company:
    without `staff_ids` and `location_ids` it has none yet, and a stay's units
    and every price are the company's own to add. The preset's words become
    the offer's own, in the company's first language; with them come what the
    preset says of time — a period's unit and its check-in and check-out, the
    travel time kept before a visit — and of paying on the spot.
    `setup.discard_draft` takes it back while it is a draft.
    """
    context, organization = _manage()
    preset = find_preset(preset_id, version)
    words = preset.raw.get("vocabulary", {})
    period, buffers = preset.raw.get("range", {}), preset.raw.get("buffers", {})
    payment = preset.raw.get("payment", {})
    policy = payment.get("policy")
    values: dict[str, Any] = {
        "name": name,
        "time_model": preset.time_model,
        "range_unit": period.get("unit", ""),
        "range_start_local": _local(period.get("startTime")),
        "range_end_local": _local(period.get("endTime")),
        "duration_minutes": duration_minutes,
        "buffer_before_minutes": buffers.get("beforeMinutes", 0),
        "buffer_after_minutes": buffers.get("afterMinutes", 0),
        "staff_count": 0 if preset.booked_staff == "none" else 1,
        # A payment ahead is the company's own choice in „Cennik”: it needs
        # orders in the plan and, for a transfer, the company's account
        # (ADR-073 §5), so a preset never fails to start for the lack of them.
        # Its terms come with the offer, ready for that choice.
        "payment_policy": policy if policy in _PLAIN_POLICIES else PaymentPolicy.NONE,
        **{field: payment[key] for field, key in _PAYMENT_TERMS.items() if key in payment},
        # What giving a booking up gives back comes with the offer too
        # (ADR-072 §8): it asks nothing of the plan, and the company changes
        # it in „Cennik” like every other term.
        **_refund_terms(preset),
        # „Rezerwacja przez stronę — wkrótce”: the team books it in the panel.
        "online": preset.online_booking == READY,
        "active": False,
        "preset_id": preset.id,
        "preset_version": preset.version,
        # The company's first language, else en, else pl (as e-mails fall back).
        "vocabulary": dict(
            words.get(source_locale(organization)) or words.get("en") or words.get("pl") or {}
        ),
        "staff_ids": staff_ids or [],
        "location_ids": location_ids or [],
    }
    return setup_write(
        context=context,
        action="service.create",
        target_id=None,
        request={"data": values},
        idempotency_key=idempotency_key,
        preview=preview,
        write=lambda: _write_service(context, organization, None, dict(values), None),
        replay=lambda item_id: _saved_service(
            organization,
            Service.all_objects.get(organization=organization, pk=item_id),
            created=True,
            replayed=True,
        ),
    )


# --- „wkrótce”: a company's sign-up for a preset that is not ready ----------


def _announced(preset_id: str) -> Preset:
    """The preset a company signs up for: one that exists and is not ready.
    A ready one is applied, not waited for (`preset_ready` on `preset_id`)."""
    versions = dict(_catalogue()).get(preset_id)
    if not versions:
        raise NotFound("Nie ma takiego wzorca.")
    preset = versions[max(versions)]
    if preset.readiness == READY:
        _refuse("Ten wzorzec jest już dostępny — możesz go użyć.", "preset_ready")
    return preset


def preset_interests() -> dict[str, PresetInterest]:
    """What the calling company signed up for, by preset."""
    context = authorize_entitled(BOOKING_MANAGE, BOOKING_ENABLED, operation=FeatureOperation.READ)
    return {
        row.preset_id: row
        for row in PresetInterest.all_objects.filter(organization_id=context.organization_id)
    }


def save_interest(
    *, preset_id: str, note: str = "", idempotency_key: str = "", preview: bool = False
) -> Saved[PresetInterest]:
    """Signs the company up for a preset that is not ready yet, with what it
    says it lacks — or rewrites that note. A setup write like every other:
    the same key again answers the first result."""
    context, organization = _manage()
    preset = _announced(preset_id)
    text = note.strip()
    if len(text) > INTEREST_NOTE_MAX:
        raise ValidationError({
            "note": [ErrorDetail(f"Najwyżej {INTEREST_NOTE_MAX} znaków.", code="max_length")]
        })

    def write() -> Saved[PresetInterest]:
        row, created = PresetInterest.all_objects.select_for_update().get_or_create(
            organization=organization,
            preset_id=preset.id,
            defaults={
                "preset_version": preset.version,
                "note": text,
                "created_by": context.actor_id,
            },
        )
        changes: dict[str, Any] = {}
        if not created and row.note != text:
            changes["note"] = {"from": row.note, "to": text}
            row.note = text
            row.save(update_fields=["note", "updated_at"])
        return Saved(row, row.id, 0, created, changes, False)

    return setup_write(
        context=context,
        action="preset_interest.save",
        target_id=None,
        request={"preset_id": preset.id, "note": text},
        idempotency_key=idempotency_key,
        preview=preview,
        write=write,
        replay=lambda item_id: Saved(
            _signed_up(organization.id, item_id), item_id, 0, False, {}, True
        ),
    )


def _signed_up(organization_id: UUID, item_id: UUID) -> PresetInterest:
    row = PresetInterest.all_objects.filter(organization_id=organization_id, pk=item_id).first()
    if row is None:
        # The key's first answer was a sign-up the company has withdrawn since.
        raise NotFound("Ten zapis został wycofany.")
    return row


def withdraw_interest(*, preset_id: str) -> bool:
    """Takes the company off a preset's list. True when it was on it; a repeat
    changes nothing and says so."""
    context, _organization = _manage()
    removed, _ = PresetInterest.all_objects.filter(
        organization_id=context.organization_id, preset_id=preset_id
    ).delete()
    return bool(removed)
