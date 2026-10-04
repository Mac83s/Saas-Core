"""Customers' part of the demo (core/organizations/demo.py): the documents a
company's customers accept — its booking terms and its privacy policy.

Each is written as a draft and approved by the owner after the second factor,
the way „Dokumenty dla klientów” does it; a text in another of the company's
languages is added to the approved version the same way. They are approved at
the company's setup (`DemoRun.setting_up`), so the bookings of its past find
them in force and the consent journal fills as the stories are played.

A document the company already has — a version in force or a draft of its own —
is left as it is. Every text opens with a line saying that it is a
demonstration sample and not legal advice.

A language of the company a document has no text in is left to the
translation engine: the part notes it in the run's memo (`translation.wanted`)
and the engine's own part orders it where the model's stand-in answers — a
document's translation always waits for a person, so it is what the demo leaves
in „Tłumaczenia → Do akceptacji”. Customers never imports the engine.

Scenario data, under `customers`: `{"documents": {kind: {locale: text}}}`; the
first locale is the one the draft is written and approved in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.locales import organization_content_locales

from .documents import (
    TRANSLATION_SOURCE,
    add_text,
    approve_draft,
    read_document,
    save_draft,
)

if TYPE_CHECKING:
    from saas_core.modules.core.organizations.demo import (
        DemoOrganization,
        DemoRun,
        DemoScenario,
    )

SAMPLE = {
    "pl": "To przykładowy tekst pokazowy, a nie porada prawna. Zastąp go własnym dokumentem, "
    "zanim przyjmiesz prawdziwe rezerwacje.",
    "en": "This is a demonstration sample, not legal advice. Replace it with your own document "
    "before you take real bookings.",
}


def _text(locale: str, *paragraphs: str) -> str:
    return "\n\n".join((SAMPLE[locale], *paragraphs))


def _privacy(name: str, contact: str) -> dict[str, str]:
    return {
        "pl": _text(
            "pl",
            f"Administratorem Twoich danych jest {name}.",
            "Dane z rezerwacji (imię i nazwisko, e-mail, telefon, termin) przetwarzamy po to, "
            "żeby przyjąć i zrealizować rezerwację oraz rozliczyć płatność. Nie przekazujemy "
            "ich nikomu poza dostawcami, którzy obsługują nasz kalendarz, pocztę i płatności.",
            "Dane rezerwacji przechowujemy tak długo, jak wymagają tego przepisy o "
            "rozliczeniach. Zgodę na oferty i promocje możesz wycofać w każdej chwili.",
            f"Możesz poprosić o wgląd w swoje dane, ich poprawienie albo usunięcie: {contact}.",
        ),
    }


def _visit_terms(name: str, contact: str) -> dict[str, str]:
    return {
        "pl": _text(
            "pl",
            f"1. Wizytę w {name} rezerwujesz przez formularz na stronie albo telefonicznie.",
            "2. Termin potwierdzamy e-mailem. Usługę „na prośbę” potwierdzamy osobno, w czasie "
            "podanym w formularzu; do tego momentu termin czeka na naszą odpowiedź.",
            "3. Płacisz na miejscu, gotówką albo kartą, chyba że usługa wymaga przelewu z góry — "
            "wtedy dane do przelewu i termin wpłaty dostajesz e-mailem, a rezerwacja jest "
            "potwierdzona po zaksięgowaniu wpłaty.",
            "4. Zmienić albo odwołać wizytę możesz z linku w wiadomości z potwierdzeniem. Przy "
            "usłudze opłaconej z góry zwracamy całość przy odwołaniu co najmniej 7 dni przed "
            "terminem i połowę przy odwołaniu co najmniej 2 dni przed terminem.",
            f"5. Pytania i reklamacje: {contact}.",
        ),
        "en": _text(
            "en",
            f"1. You book a visit at {name} through the form on our site or by phone.",
            "2. We confirm the time by e-mail. A service taken “on request” is confirmed "
            "separately, within the time the form states; until then the time waits for our "
            "answer.",
            "3. You pay on site, in cash or by card, unless the service asks for a transfer in "
            "advance — you then get the transfer details and the due date by e-mail, and the "
            "booking is confirmed once the payment is recorded.",
            "4. You can change or cancel a visit from the link in the confirmation message. For "
            "a service paid in advance we refund everything when you cancel at least 7 days "
            "before the visit and half when you cancel at least 2 days before.",
            f"5. Questions and complaints: {contact}.",
        ),
    }


def _stay_terms(name: str, contact: str) -> dict[str, str]:
    return {
        "pl": _text(
            "pl",
            f"1. Pobyt w {name} rezerwujesz na naszej stronie albo telefonicznie. Doba zaczyna "
            "się i kończy o godzinach podanych przy rezerwacji.",
            "2. Rezerwacja jest potwierdzona po wpłacie przedpłaty: 30% ceny pobytu przelewem "
            "w ciągu 3 dni. Resztę wpłacasz przelewem najpóźniej 14 dni przed przyjazdem.",
            "3. Rezygnacja co najmniej 30 dni przed przyjazdem: zwracamy całą przedpłatę. "
            "Co najmniej 14 dni przed przyjazdem: zwracamy połowę. Później przedpłata nie "
            "podlega zwrotowi. Wszystko, co wpłaciłeś ponad przedpłatę, zwracamy w całości.",
            "4. Kaucję pobieramy przy przyjeździe i oddajemy przy wyjeździe, jeśli nic nie "
            "zostało uszkodzone. Opłata miejscowa i sprzątanie końcowe są doliczane do ceny.",
            f"5. Pytania i reklamacje: {contact}.",
        ),
        "en": _text(
            "en",
            f"1. You book a stay at {name} on our site or by phone. The day begins and ends at "
            "the hours stated when you book.",
            "2. The booking is confirmed once the prepayment arrives: 30% of the price of the "
            "stay by transfer within 3 days. You transfer the rest no later than 14 days "
            "before arrival.",
            "3. Cancelling at least 30 days before arrival: we refund the whole prepayment. "
            "At least 14 days before arrival: we refund half. Later the prepayment is not "
            "refunded. Anything you paid beyond the prepayment is refunded in full.",
            "4. We take the security deposit on arrival and return it on departure if nothing "
            "was damaged. The local tourist tax and the final cleaning are added to the price.",
            f"5. Questions and complaints: {contact}.",
        ),
    }


def _rental_terms(name: str, contact: str) -> dict[str, str]:
    return {
        "pl": _text(
            "pl",
            f"1. Sprzęt w {name} rezerwujesz na dni: odbiór i zwrot w godzinach podanych przy "
            "rezerwacji, w naszej przystani.",
            "2. Płacisz na miejscu przy odbiorze. Kaucję pobieramy przy odbiorze i oddajemy "
            "przy zwrocie sprzętu w stanie, w jakim został wydany.",
            "3. Rezerwację możesz odwołać z linku w wiadomości z potwierdzeniem. Gdy pogoda "
            "nie pozwala na bezpieczne pływanie, odwołujemy rezerwację sami.",
            f"4. Pytania i reklamacje: {contact}.",
        ),
        "en": _text(
            "en",
            f"1. You book equipment at {name} by the day: pickup and return at the hours stated "
            "when you book, at our marina.",
            "2. You pay on site at pickup. We take the security deposit at pickup and return "
            "it when the equipment comes back as it was handed out.",
            "3. You can cancel a booking from the link in the confirmation message. When the "
            "weather does not allow safe paddling, we cancel the booking ourselves.",
            f"4. Questions and complaints: {contact}.",
        ),
    }


def _company(name: str, slug: str, terms: Any) -> dict[str, Any]:
    contact = f"kontakt@{slug}.test"
    return {
        "documents": {
            "booking_terms": terms(name, contact),
            # In Polish only: its English text is the translation the demo
            # leaves waiting for a person where the model's stand-in runs.
            "privacy_policy": _privacy(name, contact),
        }
    }


#: The core scenario's own companies (the default scenario leaves it to us).
DEFAULTS: dict[str, dict[str, Any]] = {
    "studio": _company("Studio Testowe", "studio-testowe", _visit_terms),
    "domki": _company("Domki nad Jeziorem", "domki-nad-jeziorem", _stay_terms),
    "kajaki": _company("Kajaki Krutynia", "kajaki-krutynia", _rental_terms),
}

NAMES = {"booking_terms": "regulamin rezerwacji", "privacy_policy": "polityka prywatności"}
#: The run's memo key under which parts leave what they want translated:
#: `{"company", "source_key", "object_id", "locale", "label"}`.
TRANSLATION_WANTED = "translation.wanted"


def _data(scenario: DemoScenario, spec: DemoOrganization) -> dict[str, Any] | None:
    data = spec.data.get("customers")
    if data is None and scenario.default:
        data = DEFAULTS.get(spec.key)
    return data


def describe(scenario: DemoScenario, spec: DemoOrganization) -> list[str]:
    data = _data(scenario, spec)
    return [
        f"{NAMES.get(kind, kind)} zatwierdzony w językach: {', '.join(texts)} "
        "(tekst pokazowy, nie porada prawna)"
        for kind, texts in (data or {}).get("documents", {}).items()
    ]


def seed_documents(run: DemoRun) -> None:
    for spec in run.scenario.organizations:
        data = _data(run.scenario, spec)
        for kind, texts in (data or {}).get("documents", {}).items():
            try:
                with run.setting_up(spec.key), run.acting(spec.key, step_up=True):
                    _document(run, spec, kind, texts)
            except (APIException, DjangoValidationError) as error:
                run.log(f"! {NAMES.get(kind, kind)} {spec.name}: {getattr(error, 'detail', error)}")


def _document(run: DemoRun, spec: DemoOrganization, kind: str, texts: dict[str, str]) -> None:
    name = NAMES.get(kind, kind)
    document = read_document(kind)["document"]
    languages = organization_content_locales(run.organizations[spec.key])
    if document["in_force"] is not None or document["draft"]:
        run.log(f"= {name} ({spec.name})")
        _want_translations(run, spec, name, document, languages)
        return
    written = [locale for locale in texts if locale in languages]
    if not written:
        return
    source, others = written[0], written[1:]
    saved = save_draft(
        kind, text=texts[source], locale=source, expected_version=document["version"]
    )
    document = approve_draft(kind, expected_version=saved["version"])["document"]
    for locale in others:
        document = add_text(
            kind,
            number=document["in_force"]["number"],
            locale=locale,
            text=texts[locale],
            expected_version=document["version"],
        )
    run.log(f"+ {name} {spec.name}: w mocy, języki {', '.join(written)}")
    _want_translations(run, spec, name, document, languages)


def _want_translations(
    run: DemoRun,
    spec: DemoOrganization,
    name: str,
    document: dict[str, Any],
    languages: tuple[str, ...],
) -> None:
    """Notes each language of the company the version in force has no text
    in and nothing waits for, for the translation engine's part."""
    version, translation = document["in_force"], document.get("translation")
    if version is None or translation is None:
        return
    for locale in languages:
        if locale in version["locales"] or locale in translation["waiting"]:
            continue
        run.memo.setdefault(TRANSLATION_WANTED, []).append({
            "company": spec.key,
            "source_key": TRANSLATION_SOURCE,
            "object_id": translation["object_id"],
            "locale": locale,
            "label": name,
        })
