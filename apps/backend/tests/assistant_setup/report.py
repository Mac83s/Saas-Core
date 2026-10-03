"""The report for the owner: what the assistant would set up today for the four
example businesses, said the way the business sees it (Polish).

Written from the configurator's answers by `test_what_the_product_can_do_today`
into `docs/assistant/co-asystent-zalozy-dzis.md`; nothing here decides
anything, it only words the four lists.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TITLES = {
    "hairdresser": "Fryzjer",
    "plumber": "Hydraulik",
    "cottages": "Domki letniskowe",
    "kayak-rental": "Wypożyczalnia kajaków",
}
#: What makes a kind of booking ready, from the bookings plan (memex
#: `saas-core-rezerwacje-uniwersalne-i-sprzedaz`: the „faza” column of its
#: preset catalogue and the owner's open questions 67 and 68). The engine for
#: stays and rentals exists; when their presets count as ready is undecided.
_RANGE = (
    "silnik pobytów i wynajmu już jest, a rodzaj rezerwacji będzie gotowy po cenniku "
    "(plan rezerwacji, faza 3) albo dopiero z formularzem publicznym (faza 5) — "
    "decyzja właściciela w toku (pytanie 67)"
)
_LATER = "odblokuje: plan rezerwacji, faza 13 (pozostałe rodzaje rezerwacji)"
_EVENTS = "odblokuje: plan rezerwacji, faza 8 (wydarzenia i zajęcia)"
PRESET_UNBLOCKS = {
    "core.specialist_visit": "odblokuje: plan rezerwacji, faza 3 (cennik i wycena)",
    "core.online_visit": _LATER,
    "core.service_at_customer": f"{_LATER}; wcześniejsza, okrojona wersja w fazie 3 — "
    "decyzja właściciela w toku (pytanie 68)",
    "core.hourly_space": _RANGE,
    "core.table_or_group": _LATER,
    "core.lodging": _RANGE,
    "core.rental": _RANGE,
    "core.care_stay": _RANGE,
    "core.exclusive_date": _RANGE,
    "core.group_class": _EVENTS,
    "core.ticketed_event": _EVENTS,
    "core.course": _EVENTS,
    "core.pickup_window": "odblokuje: plan rezerwacji, faza 9 (sklep)",
}
COMMAND_PHASE = {
    "booking.staff.add@1": "plan rezerwacji, faza 3 (dodanie osoby jako polecenie asystenta)",
    "booking.preset.apply@1": "plan rezerwacji, faza 3 (zastosowanie rodzaju rezerwacji)",
    "booking.preset.list@1": "plan rezerwacji, faza 3 (odczyt rodzajów rezerwacji)",
}
CARD_LABELS = {
    "display_name": "nazwa",
    "headline": "jedno zdanie o firmie",
    "bio": "opis",
    "contact_email": "e-mail",
    "contact_phone": "telefon",
    "contact_address": "adres",
    "city_slug": "miasto",
    "category": "kategoria",
}
FIELD_LABELS = {
    "name": "nazwa",
    "preset": "rodzaj rezerwacji",
    "duration_minutes": "czas trwania",
    "units": "liczba sztuk",
    "capacity": "liczba osób",
    "price": "cena",
    "places": "miejsca",
    "people": "osoby",
    "hours": "godziny pracy",
    "headline": "jedno zdanie o firmie",
    "description": "opis firmy",
    "activity": "czym zajmuje się firma",
    "city": "miasto",
    "category": "kategoria w katalogu firm",
    "address": "adres",
    "phone": "telefon",
    "email": "e-mail",
    "season_dates": "daty sezonów",
    "min_length": "najkrótszy pobyt",
    "photos": "zdjęcia",
}
ORIGINS = {
    "assistant": "propozycja asystenta",
    "existing_site": "z dotychczasowej strony firmy",
    "account": "z konta firmy",
    "preset_default": "wartość domyślna rodzaju rezerwacji",
    "owner": "słowa właściciela",
}
LISTS = {"place": "places", "person": "people", "offer": "offers", "hours": "people"}


def render(
    answers: Mapping[str, tuple[Mapping[str, Any], Mapping[str, Any]]],
    presets: Mapping[str, Any],
    missing_commands: list[str],
) -> str:
    labels = {preset["id"]: preset["labels"]["pl"]["name"] for preset in presets["presets"]}
    lines = [
        "# Co asystent założy dziś — cztery przykładowe firmy",
        "",
        "Ten plik pisze test, nie człowiek: "
        "`apps/backend/tests/test_assistant_configurator.py::test_what_the_product_can_do_today`.",
        "Bierze cztery przykładowe profile firm (`packages/contracts/assistant/examples/`),",
        "konto firmy tuż po rejestracji i to, co produkt naprawdę ma dziś: zarejestrowane",
        "polecenia asystenta, katalog rodzajów rezerwacji i słownik katalogu firm. Zmiana w",
        "produkcie zmienia ten plik w tym samym commicie.",
        "",
        "Asystent nie wywołuje tu modelu i niczego nie zapisuje. To wynik konfiguratora (faza A2",
        "planu asystenta): z tego, co powiedział właściciel, wylicza cztery listy.",
        "",
        "- **Ustawi od razu** — polecenia gotowe do wykonania po jednym kliknięciu zgody.",
        "- **Zapyta** — czego brakuje albo co zaproponował sam i właściciel musi potwierdzić.",
        "- **Czeka** — kroki na następną rundę albo na polecenie, którego produkt jeszcze nie ma.",
        "- **Produkt jeszcze nie umie** — czego właściciel chce, a czego nie da się dziś ustawić.",
        "",
        "| Firma | Ustawi od razu | Zapyta | Czeka | Produkt jeszcze nie umie |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, (profile, answer) in answers.items():
        lines.append(
            f"| {TITLES[name]} — {profile['company']['name']['value']} "
            f"| {len(answer['plan'])} | {len(answer['missing'])} "
            f"| {len(answer['blocked'])} | {len(answer['unsupported'])} |"
        )
    lines += [
        "",
        "## Czego dziś brakuje w produkcie",
        "",
        *(f"- polecenie `{command}` — {COMMAND_PHASE[command]}" for command in missing_commands),
        *(
            f"- rodzaj rezerwacji „{labels[preset]}” jest w przygotowaniu — "
            f"{PRESET_UNBLOCKS[preset]}"
            for preset in sorted({
                entry["detail"]
                for _profile, answer in answers.values()
                for entry in answer["unsupported"]
                if entry["code"] == "preset_not_ready"
            })
        ),
        "- ceny usług: produkt ich nie przechowuje — plan rezerwacji, faza 3 (cennik i wycena)",
        *(
            f"- miasto „{entry['detail']}” jest poza słownikiem miast katalogu firm"
            for _profile, answer in answers.values()
            for entry in answer["unsupported"]
            if entry["code"] == "city_not_in_catalog"
        ),
    ]
    for name, (profile, answer) in answers.items():
        company = profile["company"]
        lines += [
            "",
            f"## {TITLES[name]} — {company['name']['value']}, {company['city']['value']}",
            "",
            f"Właściciel powiedział: „{company['activity']['value']}”.",
            *_section("Ustawi od razu", [_step(profile, entry) for entry in answer["plan"]]),
            *_section(
                "Zapyta",
                [_question(profile, labels, entry) for entry in answer["missing"]],
            ),
            *_section("Czeka", [_blocked(profile, entry) for entry in answer["blocked"]]),
            *_section(
                "Produkt jeszcze nie umie",
                [_unsupported(profile, labels, entry) for entry in answer["unsupported"]],
            ),
        ]
    lines += [
        "",
        "## Skąd te dane",
        "",
        "- konto: odczyty przez rejestr poleceń (`organization.read`, "
        "`organization.public_locales.read`, `profiles.organization.read`, "
        "`profiles.catalog_options.read`, `booking.setup.read`) dla firmy typu `business` "
        "bez wizytówki, miejsc, osób i usług;",
        "- rodzaje rezerwacji: kontrakt `packages/contracts/booking-presets/`, dopóki "
        "polecenie `booking.preset.list@1` jest tylko zapowiedziane;",
        "- języki: oferuje je profil wdrożenia (testy liczą na profilu z polskim i "
        "angielskim, Business ma też niemiecki), więc przykład używa pary pl + en;",
        "- reguły konfiguratora mają osobne testy na zamrożonych katalogach — ten plik "
        "pokazuje stan produktu, nie reguły.",
    ]
    return "\n".join(lines) + "\n"


def _section(title: str, items: list[str]) -> list[str]:
    return ["", f"**{title}**", "", *(f"- {item}" for item in items or ["nic"])]


def _entry(profile: Mapping[str, Any], listed: str, key: str) -> Mapping[str, Any]:
    return next(entry for entry in profile.get(listed, []) if entry["key"] == key)


def _name(profile: Mapping[str, Any], listed: str, key: str) -> str:
    name = _entry(profile, listed, key).get("name")
    return str(name["value"]) if name else key


def _thing(profile: Mapping[str, Any], ref: str) -> str:
    """A step's subject in words: `offer:cut` → usługa „Strzyżenie damskie”."""
    kind, _, key = ref.partition(":")
    key = key.partition(":")[0]
    if kind == "organization":
        return "nazwa firmy"
    if kind == "languages":
        return "języki firmy"
    if kind == "card":
        return "wizytówka"
    name = _name(profile, LISTS[kind], key)
    return {
        "place": f"miejsce „{name}”",
        "person": f"osoba „{name}”",
        "offer": f"usługa „{name}”",
        "hours": f"godziny pracy: {name}",
    }[kind]


def _step(profile: Mapping[str, Any], entry: Mapping[str, Any]) -> str:
    arguments = entry["arguments"]
    kind = entry["ref"].partition(":")[0]
    if kind == "organization":
        return f"nazwę firmy: „{arguments['name']}”"
    if kind == "languages":
        return f"języki firmy: {', '.join(arguments['public_locales'])}"
    if kind == "card":
        fields = [CARD_LABELS[field] for field, value in arguments.items() if value is not None]
        return f"wizytówkę firmy: {', '.join(fields)}"
    if kind == "offer" and "service_id" not in arguments:
        return f"{_thing(profile, entry['ref'])} — wyłączona, włącza ją właściciel w panelu"
    return _thing(profile, entry["ref"])


def _subject(profile: Mapping[str, Any], key: str) -> tuple[str, str]:
    """A question's key as (whose, which field): `offers.cut.price`."""
    parts = key.split(".")
    if parts[0] in ("places", "people", "offers") and len(parts) > 2:
        return f"„{_name(profile, parts[0], parts[1])}”: ", parts[-1]
    return "", parts[-1]


def _question(
    profile: Mapping[str, Any], labels: Mapping[str, str], entry: Mapping[str, Any]
) -> str:
    whose, field = _subject(profile, entry["key"])
    if entry["kind"] == "confirm":
        proposal = labels.get(entry["proposal"], entry["proposal"])
        return (
            f"potwierdzenie — {whose}{FIELD_LABELS.get(field, field)}: „{proposal}” "
            f"({ORIGINS[entry['reason']]})"
        )
    name = whose.removesuffix(": ")
    wording = {
        "what_company_does": "czym zajmuje się firma",
        "nothing_to_sell": "co firma sprzedaje albo na co przyjmuje rezerwacje",
        "offer_needs_kind": f"jakim rodzajem rezerwacji jest {name} (wybór z listy)",
        "preset_requires": f"{whose}{FIELD_LABELS.get(field, field)}",
        "offer_needs_place": f"w którym miejscu jest {name}" if name else "gdzie firma przyjmuje",
        "offer_needs_person": f"kto wykonuje {name}" if name else "kto wykonuje usługi",
        "person_needs_hours": f"w jakich godzinach pracuje {name.strip('„”')}",
        "place_needs_name": "jak nazywa się miejsce",
        "person_needs_name": "jak nazywa się osoba",
        "card_needs_city": "w jakim mieście działa firma",
        "card_needs_category": "kategoria w katalogu firm",
    }[entry["reason"]]
    if entry["reason"] == "card_needs_category":
        options = {option["value"]: option["label"]["pl"] for option in entry["options"]}
        hint = options.get(entry["proposal"])
        wording += f" — asystent podpowie „{hint}”" if hint else " — wybór z listy, bez podpowiedzi"
    return wording


def _blocked(profile: Mapping[str, Any], entry: Mapping[str, Any]) -> str:
    thing = _thing(profile, entry["ref"])
    if entry["reason"] == "person_only":
        return f"{thing} — włączenie to krok właściciela w panelu"
    if entry["reason"] == "command_missing":
        command = entry["command"]
        return (
            f"{thing} — produkt nie ma polecenia `{command}`; odblokuje: {COMMAND_PHASE[command]}"
        )
    after = ", ".join(_thing(profile, ref) for ref in entry["waits_for"])
    return f"{thing} — w następnej rundzie, gdy będą: {after}"


def _unsupported(
    profile: Mapping[str, Any], labels: Mapping[str, str], entry: Mapping[str, Any]
) -> str:
    whose, _field = _subject(profile, f"{entry['key']}.")
    name = whose.removesuffix(": ")
    code, detail = entry["code"], entry["detail"]
    if code == "preset_not_ready":
        return (
            f"{name} — rodzaj rezerwacji „{labels[detail]}” jest w przygotowaniu; "
            f"{PRESET_UNBLOCKS[detail]}"
        )
    if code == "price_list":
        parts = entry["key"].split(".")
        price = _entry(profile, parts[0], parts[1])["price"]["value"]
        return (
            f"cena {name} "
            f"({price['amount'].replace('.', ',')} {price['currency']}) — "
            "produkt nie przechowuje cen; "
            "odblokuje: plan rezerwacji, faza 3 (cennik i wycena)"
        )
    return {
        "city_not_in_catalog": f"miasto „{detail}” — nie ma go w słowniku miast katalogu firm, "
        "więc wizytówka nie trafi do katalogu; odblokuje: dopisanie miasta do słownika "
        "(ADR-053 §7, słownik rośnie z zasięgiem sprzedaży)",
        "category_unknown": f"kategoria „{detail}” — nie ma jej w katalogu firm",
        "preset_unknown": f"{name} — rodzaj rezerwacji „{detail}” nie jest dostępny dla tej firmy",
        "language_not_offered": f"język „{detail}” — platforma go nie oferuje",
        "language_limit": f"języki: {detail} — plan firmy nie pozwala dodać kolejnego języka",
        "booking_unavailable": f"{name} — ten produkt nie ma modułu rezerwacji",
        "presets_unavailable": f"{name} — asystent nie ma jeszcze odczytu rodzajów rezerwacji",
    }[code]
