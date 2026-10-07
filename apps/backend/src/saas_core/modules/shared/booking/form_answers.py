"""What a customer answers to an offer's own fields (ADR-072 §8, slice 5j).

A booking form asks what the offer's fields say (`form_fields`); this module
is the one place that checks the answers of a booking and says how they are
kept. Every booking path — the public form, the panel, a product through
`booking.api` — hands its answers to `checked` before anything is written,
and `record_new_booking` journals the consents among them.

An answer is the customer's data, not configuration:

- it is frozen on the booking (`Appointment.form_answers`) with the question
  as the company wrote it, so a field changed or switched off later rewrites
  nothing;
- it is shown with the visit to whoever sees the customer's phone, and to
  nobody else — not in an e-mail or a notification's context, a log line, the
  history of changes, the booking's public answer, the customer's own link or
  an assistant's command;
- it leaves with the customer: `services.strip_customer_visits` clears it,
  for the anonymisation by hand and for the retention run alike.

A `consent` is not a value. Ticked, it is a line of the consent journal in the
words and the language the customer was shown (`ConsentKind.FIELD`); the
booking keeps only the mention that it was ticked. Not ticked, it is nothing.

A mandatory field binds whoever fills the form in: the customer who books for
themselves, and a staff member who books for a customer in the panel's own
dialogs (`staff_form`) — the office asks the caller what the form would have
asked. A product booking through `booking.api`, which shows no such form, may
pass answers and is asked for none.

A consent is the customer's own to give. The consent journal has no way to
say that somebody ticked a box on a customer's behalf, so only the customer's
own booking gives one: for everybody else the offer's consent fields are not
part of the form — not asked, not required, and an answer naming one is
refused.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from rest_framework.exceptions import ErrorDetail, ValidationError

from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.shared.customers.api import ConsentKind, Customer, record_consent

from .consents import SOURCE
from .models import FieldKind, FormField, Service
from .security import PUBLIC_BOOKING_ROLE

#: The longest text a customer types into one field.
MAX_TEXT_ANSWER = 200
#: A protective bound of a number, not a business rule.
MAX_NUMBER = Decimal(1_000_000_000)
#: The years a date may name: a date of birth, an arrival.
DATE_YEARS = (1900, 2100)
#: What a ticked consent sends as its value.
TICKED = "true"


@dataclass(frozen=True, slots=True)
class Answers:
    """A booking's answers, checked."""

    #: What the booking keeps: `[{field_id, name, kind, value}]`, the question
    #: in the company's language; a ticked consent with an empty value.
    kept: list[dict[str, str]] = field(default_factory=list)
    #: The consents ticked, each in the words the customer was shown.
    consents: tuple[str, ...] = ()
    #: The language those words are in.
    locale: str = ""


class _Refused(Exception):
    def __init__(self, message: str, code: str = "field_invalid") -> None:
        super().__init__(message)
        self.message, self.code = message, code


def hashed(answers: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """The answers as a booking's request is compared by, for its key; nothing
    for a booking without any, so a key from before fields still matches."""
    if not answers:
        return {}
    return {"answers": [[str(line["field_id"]), str(line.get("value") or "")] for line in answers]}


def _number(raw: str) -> str:
    try:
        value = Decimal(raw.replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        raise _Refused("Wpisz liczbę.") from None
    if not value.is_finite() or abs(value) > MAX_NUMBER:
        raise _Refused("Wpisz liczbę.")
    if value != value.quantize(Decimal("0.001")):
        raise _Refused("Najwyżej trzy miejsca po przecinku.")
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _day(raw: str) -> str:
    try:
        value = date.fromisoformat(raw)
    except ValueError:
        raise _Refused("Podaj datę w postaci RRRR-MM-DD.") from None
    if not DATE_YEARS[0] <= value.year <= DATE_YEARS[1]:
        raise _Refused("Podaj datę w postaci RRRR-MM-DD.")
    return value.isoformat()


def _read(asked: FormField, raw: str) -> str:
    """The answer as the booking keeps it, or why it is not one."""
    if asked.kind == FieldKind.NUMBER:
        return _number(raw)
    if asked.kind == FieldKind.DATE:
        return _day(raw)
    if asked.kind == FieldKind.CHOICE:
        # The company's own word for the option: a translation is only how
        # the form shows it, and one changed since the form was read is not
        # guessed at.
        if raw not in asked.option_list:
            raise _Refused("Wybierz jedną z podanych możliwości.")
        return raw
    if len(raw) > MAX_TEXT_ANSWER:
        raise _Refused(f"Najwyżej {MAX_TEXT_ANSWER} znaków.", "field_too_long")
    return raw


def _shown(consents: Sequence[FormField], locale: str) -> tuple[str, ...]:
    """Each consent in the words the form showed in `locale`: the company's
    translation where it has one, otherwise its own."""
    if not consents:
        return ()
    # Imported late: the translations' setup writes import the services.
    from .item_translations import localized_texts, translatable  # noqa: PLC0415

    texts = localized_texts(translatable("field"), consents, locale)
    return tuple(texts.get(asked.id, {}).get("name", asked.name) for asked in consents)


def checked(
    service: Service,
    given: Sequence[Mapping[str, Any]] | None,
    *,
    locale: str,
    staff_form: bool = False,
) -> Answers:
    """The answers of one booking of `service` (`[{"field_id", "value"}]`,
    every value as text), checked against the offer's fields that are
    switched on. Refuses with the field named `answers.<field id>`:
    `field_required` — a mandatory one left empty, or a mandatory consent the
    customer did not tick; `field_invalid` — not a number, not a date
    (`YYYY-MM-DD`), not one of the options; `field_too_long`; and on `answers`
    itself `field_unknown` — the offer has no such field now, or it is a
    consent and the caller is not the customer — and `field_repeated`.

    Mandatory fields are required of the customer booking for themselves and,
    with `staff_form`, of the staff member the panel's dialog showed them to.
    `locale` is the booking's language, for the wording of a consent."""
    public = require_tenant_context().role_key == PUBLIC_BOOKING_ROLE
    required = public or staff_form
    asked_now = FormField.all_objects.filter(
        organization_id=service.organization_id, service=service, active=True
    )
    if not public:
        # A consent is the customer's own to give (the journal cannot say
        # "ticked by the office for them").
        asked_now = asked_now.exclude(kind=FieldKind.CONSENT)
    fields = list(asked_now.order_by("position", "name", "id"))
    if not fields and not given:
        return Answers()
    known = {asked.id: asked for asked in fields}
    errors: dict[str, list[ErrorDetail]] = {}
    values: dict[UUID, str] = {}
    for line in given or ():
        try:
            # The form sends ids, a product through `booking.api` may send text.
            field_id = UUID(str(line.get("field_id")))
        except ValueError:
            field_id = None
        if field_id not in known:
            errors["answers"] = [ErrorDetail("Formularz nie ma takiego pola.", "field_unknown")]
        elif field_id in values:
            errors["answers"] = [ErrorDetail("To samo pole podano dwa razy.", "field_repeated")]
        elif field_id is not None:
            values[field_id] = str(line.get("value") or "").strip()
    kept: list[dict[str, str]] = []
    ticked: list[FormField] = []
    for asked in fields:
        raw = values.get(asked.id, "")
        if asked.kind == FieldKind.CONSENT and raw == "false":
            raw = ""
        if not raw:
            if asked.mandatory and required:
                errors[f"answers.{asked.id}"] = [
                    ErrorDetail(
                        "Zaznacz to pole, żeby zarezerwować."
                        if asked.kind == FieldKind.CONSENT
                        else "To pole jest wymagane.",
                        "field_required",
                    )
                ]
            continue
        if asked.kind == FieldKind.CONSENT:
            if raw != TICKED:
                errors[f"answers.{asked.id}"] = [
                    ErrorDetail("Zgoda jest zaznaczona albo nie.", "field_invalid")
                ]
                continue
            ticked.append(asked)
            value = ""
        else:
            try:
                value = _read(asked, raw)
            except _Refused as refused:
                errors[f"answers.{asked.id}"] = [ErrorDetail(refused.message, refused.code)]
                continue
        kept.append({
            "field_id": str(asked.id),
            "name": asked.name,
            "kind": asked.kind,
            "value": value,
        })
    if errors:
        raise ValidationError(errors)
    return Answers(kept=kept, consents=_shown(ticked, locale), locale=locale)


def journal(answers: Answers | None, *, customer: Customer, reference: UUID) -> None:
    """Appends the consents a customer ticked among the offer's fields, each
    word for word as shown, inside the booking's transaction (ADR-073 §9)."""
    if answers is None:
        return
    for wording in answers.consents:
        record_consent(
            customer=customer,
            kind=ConsentKind.FIELD,
            wording=wording,
            locale=answers.locale,
            source=SOURCE,
            source_reference=str(reference),
        )
