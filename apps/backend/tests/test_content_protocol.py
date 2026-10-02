"""The content translation protocol (ADR-069, ADR-070): the token grammar of a
text unit, its provenance and hash, and the facts a translation must keep."""

import pytest

from saas_core.content_protocol.facts import extract_facts
from saas_core.content_protocol.provenance import Provenance, unit_hash
from saas_core.content_protocol.tokens import (
    TOKEN_MALFORMED,
    TOKEN_MISSING,
    TOKEN_NESTING,
    TOKEN_UNEXPECTED,
    Segment,
    TokenError,
    flat_segments,
    mask,
    unmask,
    validate_tokens,
)


def test_unit_hash_ignores_spelling_that_reads_the_same_but_not_the_kind():
    assert unit_hash("text", "Za\u0301pisz  się\n") == unit_hash("text", "Zápisz się")
    assert unit_hash("text", "Kontakt") != unit_hash("inline", "Kontakt")
    assert unit_hash("text", "Kontakt") != unit_hash("text", "kontakt")


def test_provenance_round_trips_and_refuses_an_unknown_origin():
    provenance = Provenance(origin="ai", source_hash="abc", model="m", at="2026-10-02T10:00:00Z")
    assert Provenance.from_dict(provenance.as_dict()) == provenance
    assert Provenance(origin="human", source_hash="abc").as_dict() == {
        "origin": "human",
        "source_hash": "abc",
    }
    with pytest.raises(ValueError):
        Provenance(origin="robot", source_hash="abc")
    with pytest.raises(ValueError):
        Provenance(origin="ai", source_hash="")


@pytest.mark.parametrize(
    ("candidate", "problems"),
    [
        ("Read ⟦1⟧our offer⟦/1⟧ and ⟦2⟧call⟦/2⟧.", ()),
        # Word order differs between languages; the marks may move.
        ("⟦2⟧Call⟦/2⟧ after reading ⟦1⟧the offer⟦/1⟧.", ()),
        ("Read our offer and ⟦2⟧call⟦/2⟧.", (TOKEN_MISSING,)),
        ("Read ⟦1⟧our⟦/1⟧ ⟦1⟧offer⟦/1⟧ ⟦2⟧call⟦/2⟧.", (TOKEN_UNEXPECTED,)),
        ("Read ⟦3⟧our offer⟦/3⟧ ⟦2⟧call⟦/2⟧.", (TOKEN_MISSING, TOKEN_UNEXPECTED)),
        ("Read ⟦/1⟧our offer⟦1⟧ ⟦2⟧call⟦/2⟧.", (TOKEN_MALFORMED,)),
        ("Read ⟦1⟧our ⟦2⟧offer⟦/1⟧ call⟦/2⟧.", (TOKEN_MALFORMED,)),
    ],
)
def test_every_source_token_appears_once_and_pairs_are_well_formed(candidate, problems):
    source = "Przeczytaj ⟦1⟧naszą ofertę⟦/1⟧ i ⟦2⟧zadzwoń⟦/2⟧."
    assert validate_tokens(source, candidate) == problems


def test_flat_segments_read_marks_and_refuse_nesting_and_masks():
    assert flat_segments("A ⟦1⟧b⟦/1⟧ c") == [
        Segment("A ", None),
        Segment("b", 1),
        Segment(" c", None),
    ]
    for text, code in (
        ("⟦1⟧a ⟦2⟧b⟦/2⟧⟦/1⟧", TOKEN_NESTING),
        ("⟦1⟧a", TOKEN_MALFORMED),
        ("a⟦/1⟧", TOKEN_MALFORMED),
        ("a ⟦m:1⟧", TOKEN_UNEXPECTED),
    ):
        with pytest.raises(TokenError) as raised:
            flat_segments(text)
        assert raised.value.code == code
    # A bracket that forms no token is plain text.
    assert flat_segments("⟦ ⟧") == [Segment("⟦ ⟧", None)]


def test_mask_hides_contacts_addresses_and_owner_slots_and_unmask_restores_them():
    text = (
        "Napisz na biuro@firma.pl, zadzwoń +48 600 100 200 albo wejdź na "
        "https://firma.pl/oferta. ⟦1⟧Cena: 120 zł⟦/1⟧ [Uzupełnij: godziny otwarcia]"
    )
    masked, spans = mask(text)
    assert list(spans.values()) == [
        "biuro@firma.pl",
        "+48 600 100 200",
        "https://firma.pl/oferta",
        "[Uzupełnij: godziny otwarcia]",
    ]
    assert "@" not in masked
    assert "600" not in masked
    assert "120 zł" in masked
    assert "⟦1⟧" in masked
    assert unmask(masked, spans) == text
    assert validate_tokens(masked, masked.replace("⟦m:2⟧", "")) == (TOKEN_MISSING,)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Cena 1 200 zł", "Price 1.200 zł"),
        ("Cena 1\u00a0200 zł", "Price 1200 zł"),
        ("Cena 1 200,50 zł", "Price 1,200.50 zł"),
        ("Rabat 12,50%", "Discount 12.5%"),
        ("Od 8:00 do 16:00", "From 08:00 to 16:00"),
        ("Tel. +48 600 100 200", "Phone +48600100200"),
        ("Pisz: Biuro@Firma.pl", "Write: biuro@firma.pl"),
        ("Zobacz https://Firma.PL/oferta.", "See HTTPS://firma.pl/oferta"),
        ("ul. Wójcika 5, Łódź", "5 Wójcika Street, Łódź"),
        ("Kontakt", "Contact"),
    ],
)
def test_facts_compare_values_not_notation(first, second):
    assert extract_facts(first) == extract_facts(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Cena 120 zł", "Price 150 zł"),
        ("Cena 120 zł", "Price 120 PLN"),
        ("Cena 120 zł", "Price €120"),
        ("Od 8:00", "From 9:00"),
        ("Tel. 600 100 200", "Phone 600 100 201"),
        ("biuro@firma.pl", "office@firma.pl"),
        ("Gwarancja 2 lata", "Warranty 3 years"),
    ],
)
def test_facts_tell_a_changed_value(first, second):
    assert extract_facts(first) != extract_facts(second)


def test_facts_name_their_kind():
    assert extract_facts("Pakiet 1 200 zł, tel. +48 600 100 200, od 9:00, 3 sesje") == {
        ("money", "1200 zł"),
        ("phone", "+48600100200"),
        ("time", "9:00"),
        ("number", "3"),
    }
