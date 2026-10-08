"""HTML → core blocks with a loss report (plan PB2,
`docs/architecture/site-html-import.md`): what each construct becomes, that
nothing goes missing without being named, that the limits split instead of
cutting, and that the result is what the entry service and a translation take
as they are.

The rules for an underline, for words the markup put where nothing holds them
and for a link in a heading were set on a real corpus (PB2c). The fixtures
here are written for the tests: they repeat the shapes found, not the texts."""

from __future__ import annotations

import json
import re
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command

from saas_core.modules.shared.sites.block_contracts import site_block_contracts
from saas_core.modules.shared.sites.html_blocks import (
    CHANGED,
    FAQ_VERSION,
    LABEL_MAX_LENGTH,
    LOST,
    RICH_TEXT_VERSION,
    SEPARATOR_VERSION,
    SPLIT,
    TABLE_VERSION,
    HtmlConversion,
    convert_html,
    format_report,
)
from saas_core.modules.shared.sites.localized_bodies import (
    UNIT_INLINE,
    UNIT_TEXT,
    assemble,
    extract_units,
)
from saas_core.modules.shared.sites.rich_content import assert_unique_anchors
from saas_core.modules.shared.sites.services import REL_CAPABLE_BLOCKS

ASSET = "11111111-1111-4111-8111-111111111111"


def nodes(conversion: HtmlConversion, block: int = 0) -> list[dict[str, Any]]:
    assert conversion.blocks[block]["block_type"] == "core.rich_text"
    return conversion.blocks[block]["data"]["content"]


def kinds(conversion: HtmlConversion, severity: str | None = None) -> dict[str, int]:
    found: dict[str, int] = {}
    for loss in conversion.losses:
        if severity is None or loss.severity == severity:
            found[loss.kind] = found.get(loss.kind, 0) + loss.count
    return found


def types(conversion: HtmlConversion) -> list[str]:
    return [block["block_type"] for block in conversion.blocks]


def _plain_text(node: dict[str, Any]) -> str:
    return "".join(run["text"] for run in node.get("content", []))


def test_the_converter_writes_the_newest_version_of_every_block_it_makes():
    validators = site_block_contracts().validators
    for block_type, version in (
        ("core.rich_text", RICH_TEXT_VERSION),
        ("core.table", TABLE_VERSION),
        ("core.faq", FAQ_VERSION),
        ("core.separator", SEPARATOR_VERSION),
    ):
        assert max(validators[block_type]) == version


def test_paragraphs_marks_and_links_come_through_unchanged():
    conversion = convert_html(
        "<p>Zwykły, <strong>gruby</strong>, <em>pochyły</em> i "
        '<a href="https://example.com/a" rel="nofollow noopener">link</a>.</p>'
        '<p>Drugi z <a href="/cennik"><b>cennikiem</b></a>, '
        '<a href="mailto:a@example.com">pocztą</a> i&nbsp;twardą spacją.</p>'
    )
    assert conversion.losses == ()
    assert nodes(conversion) == [
        {
            "type": "paragraph",
            "content": [
                {"text": "Zwykły, "},
                {"text": "gruby", "bold": True},
                {"text": ", "},
                {"text": "pochyły", "italic": True},
                {"text": " i "},
                {"text": "link", "href": "https://example.com/a", "rel": "nofollow"},
                {"text": "."},
            ],
        },
        {
            "type": "paragraph",
            "content": [
                {"text": "Drugi z "},
                {"text": "cennikiem", "bold": True, "href": "/cennik"},
                {"text": ", "},
                {"text": "pocztą", "href": "mailto:a@example.com"},
                {"text": " i\xa0twardą spacją."},
            ],
        },
    ]
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]


def test_text_without_any_markup_is_one_paragraph():
    conversion = convert_html("Sam tekst,\n\nbez znaczników.")
    assert nodes(conversion) == [
        {"type": "paragraph", "content": [{"text": "Sam tekst, bez znaczników."}]}
    ]
    assert conversion.losses == ()
    assert convert_html("  \n ").blocks == []


def test_a_link_the_contract_refuses_keeps_its_words_and_is_named():
    conversion = convert_html(
        '<p><a href="http://old.example/x" target="_blank">stary</a>, '
        '<a href="//cdn.example/y">bez protokołu</a>, '
        '<a href="blog/wpis">względny</a>, '
        '<a href="javascript:alert(1)">skrypt</a>, '
        '<a href="">pusty</a>, <a href="/ok"></a>'
        '<a name="kotwica">bez adresu</a>.</p>'
    )
    runs = nodes(conversion)[0]["content"]
    assert [run["href"] for run in runs if "href" in run] == [
        "https://old.example/x",
        "https://cdn.example/y",
    ]
    assert "".join(run["text"] for run in runs) == (
        "stary, bez protokołu, względny, skrypt, pusty, bez adresu."
    )
    lost = {
        (loss.kind, loss.detail): loss.count for loss in conversion.losses if loss.severity == LOST
    }
    assert lost == {
        ("link_dropped", "relative address"): 1,
        ("link_dropped", "scheme javascript:"): 1,
        ("link_dropped", "empty address"): 1,
        ("link_dropped", "link without words"): 1,
    }
    changed = kinds(conversion, CHANGED)
    assert changed["link_upgraded_to_https"] == 2
    assert changed["link_target_dropped"] == 1
    assert changed["attribute_dropped"] == 1  # a[name]


def test_the_caller_may_map_legacy_addresses_before_they_are_judged():
    conversion = convert_html(
        '<p><a href="https://old.example/pl/blog/wpis">wpis</a> i '
        '<a href="rasy/owczarek">rasa</a></p>',
        rewrite_link=lambda href: ("/blog/wpis" if href.endswith("/blog/wpis") else f"/{href}"),
    )
    assert [run.get("href") for run in nodes(conversion)[0]["content"]] == [
        "/blog/wpis",
        None,
        "/rasy/owczarek",
    ]
    assert conversion.losses == ()


def test_headings_keep_their_level_where_the_contract_has_it_and_get_anchors():
    conversion = convert_html(
        '<h1>Tytuł <em>strony</em></h1><h2 id="zywienie">Żywienie</h2>'
        '<h3 id="Zła Kotwica">Наши услуги</h3><h5>Głęboko</h5><h2>Żywienie</h2>'
        "<h2> </h2>"
        '<p><a href="#zywienie">do żywienia</a>, <a href="#Zła Kotwica">po starej</a>, '
        '<a href="#nie-ma">donikąd</a></p>'
    )
    assert nodes(conversion)[:5] == [
        {"type": "heading", "level": 2, "anchor": "tytul-strony", "text": "Tytuł strony"},
        # A legacy id that is a valid anchor is kept: links to it still work.
        {"type": "heading", "level": 2, "anchor": "zywienie", "text": "Żywienie"},
        {"type": "heading", "level": 3, "anchor": "nashi-uslugi", "text": "Наши услуги"},
        {"type": "heading", "level": 4, "anchor": "gleboko", "text": "Głęboko"},
        {"type": "heading", "level": 2, "anchor": "zywienie-2", "text": "Żywienie"},
    ]
    # A link to a heading follows it to its new anchor; one to nowhere goes.
    assert [run.get("href") for run in nodes(conversion)[5]["content"]] == [
        "#zywienie",
        None,
        "#nashi-uslugi",
        None,
        None,
    ]
    assert_unique_anchors(conversion.blocks)
    changed = {
        (loss.kind, loss.detail): loss.count
        for loss in conversion.losses
        if loss.severity == CHANGED
    }
    assert changed == {
        ("heading_level_changed", "h1 → h2"): 1,
        ("heading_level_changed", "h5 → h4"): 1,
        ("heading_marks_dropped", "italic"): 1,
        ("empty_block_dropped", "h2"): 1,
    }
    assert [(loss.kind, loss.detail) for loss in conversion.losses if loss.severity == LOST] == [
        ("link_dropped", "fragment without a heading")
    ]


def test_anchors_avoid_the_ones_the_page_already_uses():
    conversion = convert_html("<h2>Kontakt</h2>", taken_anchors={"kontakt"})
    assert nodes(conversion)[0]["anchor"] == "kontakt-2"


def test_a_heading_too_long_for_one_becomes_a_bold_paragraph():
    long = "Bardzo długi śródtytuł " * 12
    conversion = convert_html(f"<h2>{long}</h2>")
    assert nodes(conversion) == [
        {"type": "paragraph", "content": [{"text": long.strip(), "bold": True}]}
    ]
    assert kinds(conversion) == {"heading_too_long": 1}


def test_a_link_in_a_heading_is_lost_and_the_report_says_in_full_where_it_pointed():
    # Longer than a sample is: the address is the loss's detail, never cut.
    address = "https://stary.example/poradnik/" + "bardzo-dlugi-adres-wpisu-" * 4
    assert len(address) > 120
    conversion = convert_html(
        f'<h2>Zobacz też: <a href="{address}">jak dobrać ramę</a></h2><p>Tekst.</p>'
        '<h3><a href="/poradnik/opony/">Opony</a> na błoto</h3><p>Tekst.</p>'
        f'<h3><a href="{address}">Jeszcze raz</a></h3><p>Tekst.</p>'
    )
    assert [node["text"] for node in nodes(conversion) if node["type"] == "heading"] == [
        "Zobacz też: jak dobrać ramę",
        "Opony na błoto",
        "Jeszcze raz",
    ]
    assert [
        (loss.severity, loss.kind, loss.detail, loss.count, loss.sample)
        for loss in conversion.losses
    ] == [
        (LOST, "heading_link_dropped", "/poradnik/opony/", 1, "Opony na błoto"),
        (LOST, "heading_link_dropped", address, 2, "Zobacz też: jak dobrać ramę"),
    ]
    # The caller's mapping of old addresses is applied before the loss is named.
    mapped = convert_html(
        f'<h2><a href="{address}">Rama</a></h2>', rewrite_link=lambda _href: "/wpisy/rama/"
    )
    assert [loss.detail for loss in mapped.losses] == ["/wpisy/rama/"]


def test_a_heading_has_one_weight_so_bold_on_a_part_of_it_is_named():
    whole = convert_html("<h2><strong>Cały gruby</strong></h2>")
    assert whole.losses == ()
    part = convert_html("<h2>Rasa: <b>owczarek</b></h2>")
    assert nodes(part)[0]["text"] == "Rasa: owczarek"
    assert [(loss.kind, loss.detail) for loss in part.losses] == [
        ("heading_marks_dropped", "bold on a part")
    ]


def test_an_underline_on_a_part_of_a_text_is_emphasis_and_becomes_bold():
    conversion = convert_html(
        "<p>To rower, który <u>nie lubi deszczu</u> i <i><u>soli</u></i>.</p>"
        "<ul><li><u>Smarowanie</u> – po każdej ulewie</li></ul>"
        "<blockquote>Rama <ins>stalowa</ins>.</blockquote>"
        "<table><tr><td>Masa</td>"
        '<td><span style="text-decoration: underline">11 kg</span></td></tr></table>'
    )
    assert nodes(conversion) == [
        {
            "type": "paragraph",
            "content": [
                {"text": "To rower, który "},
                {"text": "nie lubi deszczu", "bold": True},
                {"text": " i "},
                {"text": "soli", "bold": True, "italic": True},
                {"text": "."},
            ],
        },
        {
            "type": "list",
            "style": "bullet",
            "items": [
                {
                    "content": [
                        {"text": "Smarowanie", "bold": True},
                        {"text": " – po każdej ulewie"},
                    ]
                }
            ],
        },
        {
            "type": "quote",
            "content": [{"text": "Rama "}, {"text": "stalowa", "bold": True}, {"text": "."}],
        },
    ]
    assert conversion.blocks[1]["data"]["rows"][0]["cells"][1] == {
        "content": [{"text": "11 kg", "bold": True}]
    }
    assert [(loss.severity, loss.kind, loss.detail, loss.count) for loss in conversion.losses] == [
        (CHANGED, "underline_as_bold", "in a list item", 1),
        (CHANGED, "underline_as_bold", "in a paragraph", 1),
        (CHANGED, "underline_as_bold", "in a quote", 1),
        (CHANGED, "underline_as_bold", "in a table cell", 1),
    ]


def test_an_underline_next_to_bold_is_one_bold_run_and_on_bold_words_it_only_goes():
    conversion = convert_html(
        "<p><b>Masa:</b><u> 11 kg</u> bez pedałów.</p>"
        "<p>Zasada <b><u>najpierw hamulce</u></b> jest najważniejsza.</p>"
        '<p>Opis <a href="/modele/"><u>wszystkich modeli</u></a> jest osobno.</p>'
    )
    assert nodes(conversion) == [
        {
            "type": "paragraph",
            "content": [{"text": "Masa: 11 kg", "bold": True}, {"text": " bez pedałów."}],
        },
        {
            "type": "paragraph",
            "content": [
                {"text": "Zasada "},
                {"text": "najpierw hamulce", "bold": True},
                {"text": " jest najważniejsza."},
            ],
        },
        {
            "type": "paragraph",
            "content": [
                {"text": "Opis "},
                {"text": "wszystkich modeli", "href": "/modele/"},
                {"text": " jest osobno."},
            ],
        },
    ]
    assert [(loss.kind, loss.detail, loss.count) for loss in conversion.losses] == [
        ("underline_as_bold", "in a paragraph", 1),
        ("underline_dropped", "on a link in a paragraph", 1),
        ("underline_dropped", "on bold words in a paragraph", 1),
    ]
    assert conversion.count(LOST) == 0


def test_a_place_that_holds_plain_words_drops_the_underline_and_says_so():
    conversion = convert_html(
        "<h2>Rama <u>stalowa</u></h2><p>Tekst.</p>"
        "<table><caption><u>Wymiary</u></caption><tr><td>a</td></tr></table>"
        '<div class="question_answer"><h3>Czy <u>rdzewieje</u>?</h3><p>Nie.</p></div>'
    )
    assert nodes(conversion)[0]["text"] == "Rama stalowa"
    assert conversion.blocks[1]["data"]["caption"] == "Wymiary"
    assert conversion.blocks[2]["data"]["items"] == [
        {"question": "Czy rdzewieje?", "answer": "Nie."}
    ]
    assert [(loss.kind, loss.detail) for loss in conversion.losses] == [
        ("underline_dropped", "in a heading"),
        ("underline_dropped", "in a question or answer"),
        ("underline_dropped", "in a table caption"),
    ]


def test_a_short_paragraph_underlined_from_end_to_end_is_a_sub_heading():
    conversion = convert_html(
        "<p><u>Najczęstsze usterki napędu:</u></p><ul><li>łańcuch</li></ul>"
        # The colon outside the underline, bold with it, a line of a paragraph,
        # a question: the same label.
        "<p><u>Czyszczenie łańcucha</u>:</p><p>Po jeździe w deszczu.</p>"
        "<p><b><u>2. Ciśnienie w oponach</u></b></p><p>Co tydzień rano.</p>"
        "<p><u>Mycie:</u><br>Rzadko, <u>bez myjki</u>.</p>"
        '<p><span style="text-decoration: underline">Komu pasuje taka rama?</span></p>'
        "<p>Wysokim.</p>"
    )
    assert [node for node in nodes(conversion) if node["type"] == "heading"] == [
        {
            "type": "heading",
            "level": 3,
            "anchor": "najczestsze-usterki-napedu",
            "text": "Najczęstsze usterki napędu:",
        },
        {
            "type": "heading",
            "level": 3,
            "anchor": "czyszczenie-lancucha",
            "text": "Czyszczenie łańcucha:",
        },
        {
            "type": "heading",
            "level": 3,
            "anchor": "cisnienie-w-oponach",
            "text": "2. Ciśnienie w oponach",
        },
        {"type": "heading", "level": 3, "anchor": "mycie", "text": "Mycie:"},
        {
            "type": "heading",
            "level": 3,
            "anchor": "komu-pasuje-taka-rama",
            "text": "Komu pasuje taka rama?",
        },
    ]
    assert nodes(conversion)[7] == {
        "type": "paragraph",
        "content": [{"text": "Rzadko, "}, {"text": "bez myjki", "bold": True}, {"text": "."}],
    }
    assert kinds(conversion) == {
        "underline_as_heading": 5,
        "underline_as_bold": 1,
        "line_break_as_paragraph": 1,
    }
    assert {loss.severity for loss in conversion.losses} == {CHANGED}
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]
    assert_unique_anchors(conversion.blocks)


def test_a_label_stands_one_level_under_the_heading_above_it():
    conversion = convert_html(
        "<p><u>Bez śródtytułu nad sobą:</u></p><p>a</p>"
        "<h2>Napęd</h2><p><u>Pod h2:</u></p><p>b</p>"
        # One label does not put the next one under itself.
        "<p><u>Też pod h2:</u></p><p>c</p>"
        "<h3>Łańcuch</h3><p><u>Pod h3:</u></p><p>d</p>"
        # Under an h4 no level is left: the label stays emphasis.
        "<h4>Ogniwa</h4><p><u>Pod h4 nie ma już poziomu:</u></p><p>e</p>"
        "<h1>Koła</h1><p><u>Pod h1 zapisanym jako h2:</u></p><p>f</p>"
    )
    assert [
        (node["level"], node["text"]) for node in nodes(conversion) if node["type"] == "heading"
    ] == [
        (3, "Bez śródtytułu nad sobą:"),
        (2, "Napęd"),
        (3, "Pod h2:"),
        (3, "Też pod h2:"),
        (3, "Łańcuch"),
        (4, "Pod h3:"),
        (4, "Ogniwa"),
        (2, "Koła"),
        (3, "Pod h1 zapisanym jako h2:"),
    ]
    assert [
        (loss.kind, loss.detail, loss.count)
        for loss in conversion.losses
        if loss.kind == "underline_as_heading"
    ] == [
        ("underline_as_heading", "h3", 4),
        ("underline_as_heading", "h4", 1),
    ]
    assert {
        "type": "paragraph",
        "content": [{"text": "Pod h4 nie ma już poziomu:", "bold": True}],
    } in nodes(conversion)
    assert kinds(conversion) == {
        "underline_as_heading": 5,
        "underline_as_bold": 1,
        "heading_level_changed": 1,
    }


@pytest.mark.parametrize(
    "paragraph",
    [
        # A sentence with its full stop.
        "<p><u>Nie myj łożysk pod ciśnieniem.</u></p>",
        # Longer than a label is.
        f"<p><u>{'Rozwlekła uwaga serwisowa ' * 5}</u></p>",
        # Italics: a title or a name, not a label.
        "<p><i><u>Bellis perennis</u></i></p>",
        # A word outside the underline.
        "<p>Uwaga: <u>luźne szprychy</u></p>",
    ],
)
def test_an_underlined_paragraph_that_is_not_a_label_stays_a_paragraph(paragraph: str):
    conversion = convert_html(f"{paragraph}<p>Dalej.</p>")
    assert [node["type"] for node in nodes(conversion)] == ["paragraph", "paragraph"]
    assert all(
        run.get("bold") for run in nodes(conversion)[0]["content"] if run["text"] != "Uwaga: "
    )
    assert kinds(conversion) == {"underline_as_bold": 1}


def test_a_short_paragraph_bold_from_end_to_end_is_the_same_label_and_a_sub_heading():
    conversion = convert_html(
        "<p><b>Najczęstsze usterki hamulców:</b></p><ul><li>klocki</li></ul>"
        # The colon outside the bold, a numbered one, a line of a paragraph,
        # bold from a style, a question.
        "<p><strong>Wymiana dętki</strong>:</p><p>Na poboczu.</p>"
        "<p><b>3. Smarowanie przerzutek</b></p><p>Kroplą oleju.</p>"
        "<p><b>Zimą:</b><br>Tylko <b>pod dachem</b>.</p>"
        '<p style="font-weight: 700">Jak często centrować koło?</p><p>Raz na sezon.</p>'
        "<h2>Rama</h2><h3>Widelec</h3><p><b>Skok:</b></p><table><tr><td>100 mm</td></tr></table>"
    )
    assert [
        (node["level"], node["anchor"], node["text"])
        for block in conversion.blocks
        if block["block_type"] == "core.rich_text"
        for node in block["data"]["content"]
        if node["type"] == "heading"
    ] == [
        (3, "najczestsze-usterki-hamulcow", "Najczęstsze usterki hamulców:"),
        (3, "wymiana-detki", "Wymiana dętki:"),
        (3, "smarowanie-przerzutek", "3. Smarowanie przerzutek"),
        (3, "zima", "Zimą:"),
        (3, "jak-czesto-centrowac-kolo", "Jak często centrować koło?"),
        (2, "rama", "Rama"),
        (3, "widelec", "Widelec"),
        (4, "skok", "Skok:"),
    ]
    # Bold on a part of a paragraph is what it was.
    assert nodes(conversion)[7] == {
        "type": "paragraph",
        "content": [{"text": "Tylko "}, {"text": "pod dachem", "bold": True}, {"text": "."}],
    }
    assert [(loss.severity, loss.kind, loss.detail, loss.count) for loss in conversion.losses] == [
        (CHANGED, "bold_as_heading", "h3", 5),
        (CHANGED, "bold_as_heading", "h4", 1),
        (CHANGED, "line_break_as_paragraph", "", 1),
    ]
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]
    assert_unique_anchors(conversion.blocks)
    # An underline on a part of a bold label goes with the rest of its marks.
    mixed = convert_html("<p><b>Opony <u>bezdętkowe</u>:</b></p><p>Z mlekiem.</p>")
    assert nodes(mixed)[0]["text"] == "Opony bezdętkowe:"
    assert [(loss.kind, loss.detail) for loss in mixed.losses] == [
        ("bold_as_heading", "h3"),
        ("underline_dropped", "in a heading"),
    ]


@pytest.mark.parametrize(
    "html",
    [
        # A bold sentence is emphasis: a statement, an exclamation.
        "<p><b>Kask zapinamy pod brodą.</b></p><p>Dalej.</p>",
        "<p><b>Tak, ale tylko na suchym asfalcie!</b></p><ul><li>raz</li></ul>",
        # Longer than a label is.
        f"<p><b>{'Rozwlekła uwaga serwisowa ' * 5}</b></p><p>Dalej.</p>",
        # A link or italics in it.
        '<p><b><a href="/serwis/">Cennik serwisu</a></b></p><p>Dalej.</p>',
        "<p><b><i>Bellis perennis</i></b></p><p>Dalej.</p>",
        # A bold lead-in with words outside the bold.
        "<p><b>Uwaga:</b> luźne szprychy</p><p>Dalej.</p>",
        # It introduces sections with headings of their own, it names none.
        "<p><b>Napęd ma trzy zespoły:</b></p><h3>Rama</h3><p>Dalej.</p>",
        # The last words of the text name nothing.
        "<p>Wcześniej.</p><p><b>Do zobaczenia na trasie</b></p>",
        # Under an h4 no level is left.
        "<h4>Ogniwa</h4><p><b>Spinka:</b></p><p>Dalej.</p>",
        # In a list, a quote or a cell bold is a mark of the words.
        "<ul><li><b>Spinka:</b></li><li>dwie</li></ul>",
        "<blockquote><b>Spinka:</b></blockquote><p>Dalej.</p>",
    ],
)
def test_bold_that_is_not_a_label_stays_as_it_was_and_nothing_is_reported(html: str):
    conversion = convert_html(html)
    found = [node for node in nodes(conversion) if node["type"] == "heading"]
    assert [node["text"] for node in found] == [
        text for text in ("Rama", "Ogniwa") if f">{text}</h" in html
    ]
    assert "bold_as_heading" not in kinds(conversion)
    assert conversion.losses == ()
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]


def test_bold_the_converter_gave_is_not_a_label():
    # A definition's term and the header line of a table too wide for a block
    # are bold because the converter wrote them so.
    terms = convert_html("<dl><dt>Piasta</dt><dd>Środek koła.</dd></dl>")
    assert nodes(terms) == [
        {"type": "paragraph", "content": [{"text": "Piasta", "bold": True}]},
        {"type": "paragraph", "content": [{"text": "Środek koła."}]},
    ]
    wide = convert_html(
        "<table><tr>"
        + "".join(f"<th>k{n}</th>" for n in range(13))
        + "</tr><tr>"
        + "".join(f"<td>w{n}</td>" for n in range(13))
        + "</tr></table>"
    )
    assert [node["type"] for node in nodes(wide)] == ["paragraph", "paragraph"]
    assert "bold_as_heading" not in kinds(terms) | kinds(wide)


def test_a_label_is_as_long_as_the_limit_and_not_a_character_more():
    at_limit = "Ż" * LABEL_MAX_LENGTH
    assert nodes(convert_html(f"<p><u>{at_limit}</u></p><p>x</p>"))[0]["type"] == "heading"
    assert nodes(convert_html(f"<p><u>{at_limit}ż</u></p><p>x</p>"))[0]["type"] == "paragraph"


def test_a_label_with_nothing_after_it_labels_nothing_and_stays_emphasis():
    conversion = convert_html("<p>Tekst.</p><p><u>Na koniec:</u></p>")
    assert nodes(conversion) == [
        {"type": "paragraph", "content": [{"text": "Tekst."}]},
        {"type": "paragraph", "content": [{"text": "Na koniec:", "bold": True}]},
    ]
    assert kinds(conversion) == {"underline_as_bold": 1}
    # A table or questions after it are something to label.
    for following in (
        "<table><tr><td>a</td></tr></table>",
        '<div class="question_answer"><h3>Czy rdzewieje?</h3><p>Nie.</p></div>',
    ):
        labelled = convert_html(f"<h2>Rama</h2><p><u>Wymiary:</u></p>{following}")
        assert [(node["type"], node.get("text")) for node in nodes(labelled)] == [
            ("heading", "Rama"),
            ("heading", "Wymiary:"),
        ]
        assert len(labelled.blocks) == 2
    # A rule ends what stood before it, and a heading begins something else.
    for following in ("<hr><p>Dalej.</p>", "<h3>Koła</h3><p>Dalej.</p>"):
        closed = convert_html(f"<h2>Rama</h2><p><u>Wymiary:</u></p>{following}")
        assert nodes(closed)[1] == {
            "type": "paragraph",
            "content": [{"text": "Wymiary:", "bold": True}],
        }
        assert "underline_as_heading" not in kinds(closed)


def test_a_label_right_before_another_label_introduces_a_series_and_stays_as_it_was():
    conversion = convert_html(
        "<p><b>Rodzaje hamulców:</b></p>"
        "<p><b>1. Szczękowe:</b></p><p>Lekkie.</p>"
        "<p><b>2. Tarczowe:</b></p><ul><li>pewne w deszczu</li></ul>"
        # The same with an underline first, and three in a row.
        "<p><u>Rodzaje opon:</u></p><p><b>Szosowe</b></p><p>Wąskie.</p>"
        "<p><b>Przegląd:</b></p><p><b>Wiosną:</b></p><p><b>Łańcuch</b></p><p>Do wymiany.</p>"
    )
    assert [
        (node["type"], node.get("text") or _plain_text(node)) for node in nodes(conversion)
    ] == [
        ("paragraph", "Rodzaje hamulców:"),
        ("heading", "1. Szczękowe:"),
        ("paragraph", "Lekkie."),
        ("heading", "2. Tarczowe:"),
        ("list", ""),
        ("paragraph", "Rodzaje opon:"),
        ("heading", "Szosowe"),
        ("paragraph", "Wąskie."),
        ("paragraph", "Przegląd:"),
        ("paragraph", "Wiosną:"),
        ("heading", "Łańcuch"),
        ("paragraph", "Do wymiany."),
    ]
    # What introduces the series keeps its mark: bold, or bold for an underline.
    for index in (0, 5, 8, 9):
        assert all(run.get("bold") for run in nodes(conversion)[index]["content"])
    assert [(loss.kind, loss.detail, loss.count) for loss in conversion.losses] == [
        ("bold_as_heading", "h3", 4),
        ("underline_as_bold", "in a paragraph", 1),
    ]


def test_marks_from_inline_style_count_and_other_declarations_are_named():
    conversion = convert_html(
        '<p style="text-align: center"><span style="font-weight: 700; color: red">gruby</span> '
        '<b><span style="font-weight: normal">zwykły</span></b> '
        '<span style="font-style: italic" class="lead">pochyły</span></p>'
    )
    assert nodes(conversion)[0]["content"] == [
        {"text": "gruby", "bold": True},
        {"text": " zwykły "},
        {"text": "pochyły", "italic": True},
    ]
    assert {(loss.kind, loss.detail) for loss in conversion.losses} == {
        ("style_dropped", "text-align"),
        ("style_dropped", "color"),
        ("class_dropped", "span.lead"),
    }


def test_marks_the_contract_has_no_word_for_are_named_and_their_text_stays():
    conversion = convert_html(
        "<p>10 m<sup>2</sup>, H<sub>2</sub>O, <s>stara cena</s>, <code>kod</code>, "
        "<mark>zaznaczone</mark>, <unknown-tag>obce</unknown-tag></p>"
    )
    assert nodes(conversion)[0]["content"] == [
        {"text": "10 m2, H2O, stara cena, kod, zaznaczone, obce"}
    ]
    assert {(loss.kind, loss.detail) for loss in conversion.losses} == {
        ("superscript_flattened", ""),
        ("subscript_flattened", ""),
        ("strikethrough_dropped", "s"),
        ("code_mark_dropped", "code"),
        ("tag_unwrapped", "mark"),
        ("tag_unwrapped", "unknown-tag"),
    }
    assert conversion.count(LOST) == 0


def test_lists_keep_two_levels_and_flatten_what_is_deeper():
    conversion = convert_html(
        '<ol start="3"><li>Pierwszy</li><li><p>Drugi</p><ul><li>Dwa a'
        "<ul><li>głębiej</li></ul></li><li>Dwa b</li></ul></li>"
        "<li><ul><li>samo zagnieżdżenie</li></ul></li><li> </li></ol>"
    )
    assert nodes(conversion) == [
        {
            "type": "list",
            "style": "ordered",
            "items": [
                {"content": [{"text": "Pierwszy"}]},
                {
                    "content": [{"text": "Drugi"}],
                    "children": {
                        "style": "bullet",
                        "items": [
                            {"content": [{"text": "Dwa a"}]},
                            {"content": [{"text": "głębiej"}]},
                            {"content": [{"text": "Dwa b"}]},
                        ],
                    },
                },
                {
                    "content": [{"text": "–"}],
                    "children": {
                        "style": "bullet",
                        "items": [{"content": [{"text": "samo zagnieżdżenie"}]}],
                    },
                },
            ],
        }
    ]
    assert kinds(conversion) == {
        "list_numbering_dropped": 1,
        "list_nesting_flattened": 1,
        "list_item_without_text": 1,
        "empty_block_dropped": 1,
    }
    # The dash an item without words got is the converter's, and counted so.
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]


def test_a_list_over_the_limit_becomes_several_lists():
    items = "".join(f"<li>Pozycja {number}</li>" for number in range(1, 96))
    conversion = convert_html(f"<ul>{items}</ul>")
    lists = nodes(conversion)
    assert [len(node["items"]) for node in lists] == [40, 40, 15]
    assert lists[2]["items"][-1] == {"content": [{"text": "Pozycja 95"}]}
    assert [(loss.severity, loss.kind, loss.count) for loss in conversion.losses] == [
        (SPLIT, "list_split", 1)
    ]


def test_a_quote_is_one_run_with_its_source():
    conversion = convert_html(
        "<blockquote><p>Pies to <em>przyjaciel</em>.</p><p>Zawsze.</p>"
        "<cite>Jan Kowalski, hodowca</cite></blockquote>"
        "<blockquote>Krótko.</blockquote>"
    )
    assert nodes(conversion) == [
        {
            "type": "quote",
            "content": [
                {"text": "Pies to "},
                {"text": "przyjaciel", "italic": True},
                {"text": ". Zawsze."},
            ],
            "source": "Jan Kowalski, hodowca",
        },
        {"type": "quote", "content": [{"text": "Krótko."}]},
    ]
    assert kinds(conversion) == {"blocks_joined": 1}
    marked = convert_html("<blockquote>Tak.<cite><em>Kronika</em>, 1920</cite></blockquote>")
    assert nodes(marked)[0]["source"] == "Kronika, 1920"
    assert [(loss.kind, loss.detail) for loss in marked.losses] == [
        ("quote_source_marks_dropped", "em")
    ]


def test_a_rule_is_a_separator_block_between_two_texts():
    conversion = convert_html("<p>Przed.</p><hr><p>Po.</p>")
    assert conversion.blocks == [
        {
            "block_type": "core.rich_text",
            "schema_version": 4,
            "data": {"content": [{"type": "paragraph", "content": [{"text": "Przed."}]}]},
        },
        {"block_type": "core.separator", "schema_version": 1, "data": {"layout": "line"}},
        {
            "block_type": "core.rich_text",
            "schema_version": 4,
            "data": {"content": [{"type": "paragraph", "content": [{"text": "Po."}]}]},
        },
    ]
    assert conversion.losses == ()


TABLE = """
<p>Wstęp.</p>
<table class="compare" style="width: 100%">
  <caption>Porównanie <b>ras</b></caption>
  <colgroup><col style="width: 40%"><col><col></colgroup>
  <thead><tr><th>Rasa</th><th>Waga</th><th>Wzrost</th></tr></thead>
  <tbody>
    <tr><th scope="row">Owczarek</th><td>30–40 kg</td><td>60 cm</td></tr>
    <tr><th scope="row">Jamnik</th>
      <td colspan="2">mały, zob. <a href="/rasy/jamnik">opis</a></td></tr>
    <tr><th scope="row">Mops</th>
      <td rowspan="2"><p>8 kg</p><p>czasem więcej</p></td><td>30 cm</td></tr>
    <tr><th scope="row">Buldog</th><td>35 cm</td></tr>
  </tbody>
  <tfoot><tr><td>Źródło</td><td>własne</td><td></td></tr></tfoot>
</table>
<p>Zakończenie.</p>
"""


def test_a_table_is_a_block_of_its_own_with_caption_headers_and_cells():
    conversion = convert_html(TABLE)
    assert types(conversion) == ["core.rich_text", "core.table", "core.rich_text"]
    cell = lambda text: {"content": [{"text": text}]}  # noqa: E731
    assert conversion.blocks[1] == {
        "block_type": "core.table",
        "schema_version": 1,
        "data": {
            "caption": "Porównanie ras",
            # The first row is the head, and every body row starts with a header cell.
            "header": "row",
            "rows": [
                {"cells": [cell("Rasa"), cell("Waga"), cell("Wzrost")]},
                {"cells": [cell("Owczarek"), cell("30–40 kg"), cell("60 cm")]},
                {
                    "cells": [
                        cell("Jamnik"),
                        {
                            "content": [
                                {"text": "mały, zob. "},
                                {"text": "opis", "href": "/rasy/jamnik"},
                            ]
                        },
                        {},
                    ]
                },
                {"cells": [cell("Mops"), cell("8 kg czasem więcej"), cell("30 cm")]},
                # The cell above reached into this row: its place stays empty.
                {"cells": [cell("Buldog"), {}, cell("35 cm")]},
                {"cells": [cell("Źródło"), cell("własne"), {}]},
            ],
        },
    }
    assert {(loss.kind, loss.detail): loss.count for loss in conversion.losses} == {
        ("class_dropped", "table.compare"): 1,
        ("style_dropped", "width"): 1,
        ("caption_marks_dropped", "table"): 1,
        ("table_column_widths_dropped", "colgroup"): 1,
        ("table_span_flattened", "2×1 cells"): 1,
        ("table_span_flattened", "1×2 cells"): 1,
        ("blocks_joined", "in a table cell"): 1,
        ("table_footer_as_rows", ""): 1,
        # The footer row has no header cell, so the first column is not one.
        ("table_header_cell_as_data", ""): 1,
    }
    assert conversion.count(LOST) == 0
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]


def test_a_table_names_its_rows_when_every_body_row_starts_with_a_header_cell():
    conversion = convert_html(
        "<table><tr><th></th><th>Mały</th></tr>"
        "<tr><th>Kąpiel</th><td>80 zł</td></tr><tr><th>Strzyżenie</th><td>120 zł</td></tr></table>"
        "<table><tr><td>a</td><td>b</td></tr></table>"
    )
    assert conversion.blocks[0]["data"]["header"] == "both"
    assert conversion.blocks[0]["data"]["rows"][0] == {
        "cells": [{}, {"content": [{"text": "Mały"}]}]
    }
    assert conversion.blocks[1]["data"] == {
        "header": "none",
        "rows": [{"cells": [{"content": [{"text": "a"}]}, {"content": [{"text": "b"}]}]}],
    }
    assert conversion.losses == ()


def test_a_table_over_the_row_limit_is_cut_and_repeats_its_header():
    body = "".join(f"<tr><td>{number}</td><td>x</td></tr>" for number in range(1, 251))
    conversion = convert_html(
        f"<table><caption>Długa</caption><thead><tr><th>Nr</th><th>X</th></tr></thead>{body}</table>"
    )
    assert types(conversion) == ["core.table"] * 3
    assert [len(block["data"]["rows"]) for block in conversion.blocks] == [120, 120, 13]
    for block in conversion.blocks:
        assert block["data"]["caption"] == "Długa"
        assert block["data"]["rows"][0]["cells"][0] == {"content": [{"text": "Nr"}]}
    assert conversion.blocks[2]["data"]["rows"][-1]["cells"][0] == {"content": [{"text": "250"}]}
    assert [(loss.severity, loss.kind, loss.detail) for loss in conversion.losses] == [
        (SPLIT, "table_split", "251 rows")
    ]
    # The repeated caption and header are the converter's words, not new text.
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]


def test_a_table_wider_than_the_block_becomes_lines_of_text():
    row = "".join(f"<td>k{number}</td>" for number in range(1, 15))
    conversion = convert_html(f"<table><caption>Szeroka</caption><tr>{row}</tr></table>")
    assert types(conversion) == ["core.rich_text"]
    assert nodes(conversion)[0] == {"type": "paragraph", "content": [{"text": "Szeroka"}]}
    assert nodes(conversion)[1]["content"][0]["text"].startswith("k1 – k2 – k3")
    assert kinds(conversion) == {"table_too_wide": 1}
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]


def test_an_empty_row_is_named_and_a_caption_whose_picture_cannot_stand_is_kept():
    conversion = convert_html("<table><tr></tr><tr><td>a</td></tr></table>")
    assert conversion.blocks[0]["data"]["rows"] == [{"cells": [{"content": [{"text": "a"}]}]}]
    assert [(loss.kind, loss.detail) for loss in conversion.losses] == [
        ("empty_block_dropped", "tr")
    ]
    figure = convert_html(
        '<figure><ul><li><img src="https://cdn.example/a.jpg" alt="Pies"> w liście</li></ul>'
        "<figcaption>Podpis zostaje</figcaption></figure>",
        image_assets={"https://cdn.example/a.jpg": ASSET},
    )
    assert nodes(figure)[-1] == {"type": "paragraph", "content": [{"text": "Podpis zostaje"}]}
    assert [(loss.severity, loss.kind, loss.detail) for loss in figure.losses] == [
        (LOST, "image_dropped", "in a list item")
    ]
    assert figure.stats["characters_in"] == figure.stats["characters_out"]


def test_words_a_table_has_no_cell_for_stand_in_front_of_the_table():
    conversion = convert_html(
        "<p>Przed.</p><table>luzem<tr>w <b>wierszu</b><td>komórka</td></tr>"
        "<tbody><p>w części</p><tr><td>druga</td></tr></tbody><div>w bloku</div></table>"
    )
    assert types(conversion) == ["core.rich_text", "core.table"]
    assert nodes(conversion) == [
        {"type": "paragraph", "content": [{"text": "Przed."}]},
        {"type": "paragraph", "content": [{"text": "luzem"}]},
        {"type": "paragraph", "content": [{"text": "w "}, {"text": "wierszu", "bold": True}]},
        {"type": "paragraph", "content": [{"text": "w części"}]},
        {"type": "paragraph", "content": [{"text": "w bloku"}]},
    ]
    assert conversion.blocks[1]["data"]["rows"] == [
        {"cells": [{"content": [{"text": "komórka"}]}]},
        {"cells": [{"content": [{"text": "druga"}]}]},
    ]
    assert [(loss.severity, loss.kind, loss.detail, loss.count) for loss in conversion.losses] == [
        (CHANGED, "table_text_as_paragraph", "inside <table>", 2),
        (CHANGED, "table_text_as_paragraph", "inside <tbody>", 1),
        (CHANGED, "table_text_as_paragraph", "inside <tr>", 1),
    ]
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]
    # A cell written outside a row keeps its words too.
    bare = convert_html("<table><td>bez wiersza</td></table>")
    assert nodes(bare) == [{"type": "paragraph", "content": [{"text": "bez wiersza"}]}]
    assert bare.count(LOST) == 0


def test_words_in_a_list_outside_its_items_are_an_item_of_their_own():
    conversion = convert_html(
        # An item closed too early: the rest of its sentence is left in the list.
        "<ul><li>Dokręć śrubę</li> – ale dopiero gdy <b>mostek</b> stoi prosto</li>"
        "<li>Sprawdź hamulce</li></ul>"
        # Words before the first item, words around an element, and the same
        # one level down.
        "<ol>Kolejność:<li>raz<ul><li>a</li>luzem niżej<li>b</li></ul></li>"
        "<span>dwa</span> i pół</ol>"
    )
    assert nodes(conversion) == [
        {
            "type": "list",
            "style": "bullet",
            "items": [
                {"content": [{"text": "Dokręć śrubę"}]},
                {
                    "content": [
                        {"text": "– ale dopiero gdy "},
                        {"text": "mostek", "bold": True},
                        {"text": " stoi prosto"},
                    ]
                },
                {"content": [{"text": "Sprawdź hamulce"}]},
            ],
        },
        {
            "type": "list",
            "style": "ordered",
            "items": [
                {"content": [{"text": "Kolejność:"}]},
                {
                    "content": [{"text": "raz"}],
                    "children": {
                        "style": "bullet",
                        "items": [
                            {"content": [{"text": "a"}]},
                            {"content": [{"text": "luzem niżej"}]},
                            {"content": [{"text": "b"}]},
                        ],
                    },
                },
                {"content": [{"text": "dwa i pół"}]},
            ],
        },
    ]
    assert [(loss.severity, loss.kind, loss.detail, loss.count) for loss in conversion.losses] == [
        (CHANGED, "list_text_as_item", "inside <ol>", 2),
        (CHANGED, "list_text_as_item", "inside <ul>", 2),
        (CHANGED, "stray_end_tag", "li", 1),
    ]
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]
    # One element where an item should be is read as that item, as before.
    lone = convert_html("<ul><li>raz</li><p>dwa</p></ul>")
    assert nodes(lone)[0]["items"] == [
        {"content": [{"text": "raz"}]},
        {"content": [{"text": "dwa"}]},
    ]
    assert [(loss.kind, loss.detail) for loss in lone.losses] == [("tag_unwrapped", "p in a list")]


@pytest.mark.parametrize(
    ("html", "content", "tag"),
    [
        # `<` where the `>` was.
        (
            "<ul><li><b<Rozmiar:</b> 54 cm</li></ul>",
            [{"text": "Rozmiar:", "bold": True}, {"text": " 54 cm"}],
            "b",
        ),
        # A whole item inside its own opening tag.
        (
            "<ul><li<Rozmiar: 52–56 cm (ok. 11 kg)</li></ul>",
            [{"text": "Rozmiar: 52–56 cm (ok. 11 kg)"}],
            "li",
        ),
        # A space, a slash or a full stop where the `>` was.
        (
            "<ul><li>co <b usztywnia ramę</b> w zakręcie</li></ul>",
            [{"text": "co "}, {"text": "usztywnia ramę", "bold": True}, {"text": " w zakręcie"}],
            "b",
        ),
        (
            "<ul><li><b/miękkie siodło</b></li></ul>",
            [{"text": "miękkie siodło", "bold": True}],
            "b",
        ),
        (
            "<ul><li>zapobiega <i.pękaniu szprych</i></li></ul>",
            [{"text": "zapobiega "}, {"text": "pękaniu szprych", "italic": True}],
            "i",
        ),
        # Nothing where the `>` was: the name ends where the word begins, or
        # the closing tag names it.
        (
            "<ul><li><bZębatki i przerzutki:</b></li></ul>",
            [{"text": "Zębatki i przerzutki:", "bold": True}],
            "b",
        ),
        ("<ul><li><bЭто новая рама</b></li></ul>", [{"text": "Это новая рама", "bold": True}], "b"),
        ("<ul><li><busztywnia ramę</b></li></ul>", [{"text": "usztywnia ramę", "bold": True}], "b"),
        ("<ul><LI<Rozmiar: 54 cm</LI></ul>", [{"text": "Rozmiar: 54 cm"}], "li"),
        # Only the `>` is missing: the tag after it is a tag, not words.
        (
            "<ul><li<b>Rozmiar:</b> 54 cm</li></ul>",
            [{"text": "Rozmiar:", "bold": True}, {"text": " 54 cm"}],
            "li",
        ),
        # A `=` among the words does not make them attributes.
        (
            "<ul><li><b<Skok = 100 mm</b> z przodu</li></ul>",
            [{"text": "Skok = 100 mm", "bold": True}, {"text": " z przodu"}],
            "b",
        ),
    ],
)
def test_an_opening_tag_that_lost_its_bracket_gives_back_the_words_it_swallowed(
    html: str, content: list[dict[str, Any]], tag: str
):
    conversion = convert_html(html)
    assert nodes(conversion) == [
        {"type": "list", "style": "bullet", "items": [{"content": content}]}
    ]
    broken = re.search(r"<[a-zA-Z]+[^<>]*<[^>]*>", html)
    assert broken is not None
    raw = broken.group()
    assert [(loss.severity, loss.kind, loss.detail, loss.sample) for loss in conversion.losses] == [
        (CHANGED, "opening_tag_repaired", tag, raw)
    ]
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]


def test_a_broken_opening_tag_that_runs_into_the_next_one_keeps_both():
    conversion = convert_html("<pDlatego rama wymaga <b>przeglądu</b> co rok.</p><p>Dalej.</p>")
    assert nodes(conversion) == [
        {
            "type": "paragraph",
            "content": [
                {"text": "Dlatego rama wymaga "},
                {"text": "przeglądu", "bold": True},
                {"text": " co rok."},
            ],
        },
        {"type": "paragraph", "content": [{"text": "Dalej."}]},
    ]
    assert kinds(conversion) == {"opening_tag_repaired": 1}


def test_a_broken_tag_nothing_can_read_is_named_as_lost_and_a_tag_with_attributes_is_left_alone():
    unread = convert_html("<p>Przed <xyz<słowa w środku</xyz> po.</p>")
    assert (LOST, "text_dropped", "inside a broken tag", "<xyz<słowa w środku</xyz>") in [
        (loss.severity, loss.kind, loss.detail, loss.sample) for loss in unread.losses
    ]
    # Cut off before the next tag could end it: words nothing tells from attributes.
    cut = convert_html("<p>raz</p><pA na koniec dwa słowa")
    assert nodes(cut) == [{"type": "paragraph", "content": [{"text": "raz"}]}]
    assert [(loss.severity, loss.kind, loss.detail, loss.sample) for loss in cut.losses] == [
        (LOST, "text_dropped", "inside a broken tag", "<pA na koniec dwa słowa")
    ]
    # `=` says attributes, not words: what a browser reads stays what is read.
    attributes = convert_html(
        '<p><a href="/x" title="a<b">link</a> i <span class="x" <b>tekst</b></p>'
    )
    assert "opening_tag_repaired" not in kinds(attributes)
    assert nodes(attributes)[0]["content"][0] == {"text": "link", "href": "/x"}


@pytest.mark.parametrize(
    ("html", "cut"),
    [
        ("<ol><li>raz</li><li>dwa</li> </", "</"),
        ("<ul><li>raz</li><li><strong>dwa</strong></", "</"),
        ("<p>raz</p><ul><li>dwa</li></ul><p", "<p"),
        ('<p>raz</p><p>dwa</p><a href="/x', '<a href="/x'),
    ],
)
def test_a_document_cut_off_inside_a_tag_ends_before_that_tag(html: str, cut: str):
    conversion = convert_html(html)
    written = json.dumps(conversion.blocks, ensure_ascii=False)
    assert "<" not in written
    assert "raz" in written
    assert "dwa" in written
    assert [(loss.severity, loss.kind, loss.sample) for loss in conversion.losses] == [
        (CHANGED, "unfinished_tag_dropped", cut)
    ]
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"] == 6
    # A name cut in the middle is still only the beginning of a tag.
    assert kinds(convert_html("<p>raz</p></blockq")) == {"unfinished_tag_dropped": 1}
    # A sign that is not the beginning of a tag is a word like any other.
    assert nodes(convert_html("<p>mniej niż <"))[0]["content"] == [{"text": "mniej niż <"}]
    assert nodes(convert_html("<p>koła <29 cali"))[0]["content"] == [{"text": "koła <29 cali"}]


FAQ = """
<h2>Najczęstsze pytania</h2>
<div class="question_answer"><h3>Ile żyje owczarek?</h3>
  <p>Około <b>12 lat</b>.</p><p>Bywa dłużej.</p></div>
<div class="question_answer"><h3>Czy linieje?</h3><p>Tak, dwa razy w roku.</p></div>
<p>Po pytaniach.</p>
"""


def test_a_run_of_questions_and_answers_is_one_faq_block():
    conversion = convert_html(FAQ)
    assert types(conversion) == ["core.faq", "core.rich_text"]
    assert conversion.blocks[0] == {
        "block_type": "core.faq",
        "schema_version": 3,
        "data": {
            # The heading right above the questions names the block.
            "title": "Najczęstsze pytania",
            "items": [
                {"question": "Ile żyje owczarek?", "answer": "Około 12 lat.\n\nBywa dłużej."},
                {"question": "Czy linieje?", "answer": "Tak, dwa razy w roku."},
            ],
        },
    }
    assert kinds(conversion) == {
        "faq_heading_as_title": 1,
        "faq_marks_dropped": 1,
        "faq_paragraphs_joined": 1,
    }
    assert conversion.count(LOST) == 0


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        ('<p>Zobacz <a href="/karma">karmę</a>.</p>', "a link in an answer"),
        ("<ul><li>raz</li></ul>", "<ul> in an answer"),
        (f"<p>{'x' * 2001}</p>", "an answer over 2000 characters"),
        ("", "an empty question or answer"),
    ],
)
def test_a_group_an_faq_cannot_hold_whole_stays_text(answer: str, reason: str):
    conversion = convert_html(
        '<div class="question_answer"><h3>Czy linieje?</h3><p>Tak.</p></div>'
        f'<div class="question_answer"><h3>Co je?</h3>{answer}</div>'
    )
    assert types(conversion) == ["core.rich_text"]
    content = nodes(conversion)
    assert content[0] == {
        "type": "heading",
        "level": 3,
        "anchor": "czy-linieje",
        "text": "Czy linieje?",
    }
    assert content[2]["text"] == "Co je?"
    assert [(loss.kind, loss.detail) for loss in conversion.losses] == [
        ("faq_kept_as_text", reason)
    ]
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]


def test_an_image_needs_a_media_asset_and_words_for_who_does_not_see_it():
    html = (
        '<p>Tekst <img src="https://cdn.example/a.jpg" alt="Pies na łące" width="640"> dalej.</p>'
        '<figure><img src="https://cdn.example/b.jpg"><figcaption>Szczeniak</figcaption></figure>'
        '<img src="https://cdn.example/c.jpg" alt="Bez zasobu">'
    )
    conversion = convert_html(
        html,
        image_assets={"https://cdn.example/a.jpg": ASSET, "https://cdn.example/b.jpg": ASSET},
        default_image_alt="Zdjęcie do wpisu",
    )
    assert conversion.images == (
        "https://cdn.example/a.jpg",
        "https://cdn.example/b.jpg",
        "https://cdn.example/c.jpg",
    )
    assert nodes(conversion) == [
        {"type": "paragraph", "content": [{"text": "Tekst dalej."}]},
        {"type": "figure", "image": {"asset_id": ASSET, "alt": "Pies na łące"}},
        {
            "type": "figure",
            "image": {"asset_id": ASSET, "alt": "Zdjęcie do wpisu"},
            "caption": "Szczeniak",
        },
    ]
    assert {(loss.severity, loss.kind, loss.detail) for loss in conversion.losses} == {
        (CHANGED, "attribute_dropped", "img[width]"),
        (CHANGED, "image_moved_after_paragraph", ""),
        (LOST, "image_dropped", "no media asset given"),
    }
    # A first pass with no assets names every picture and keeps the caption.
    first = convert_html(html)
    assert kinds(first, LOST) == {"image_dropped": 3}
    assert nodes(first)[-1] == {"type": "paragraph", "content": [{"text": "Szczeniak"}]}
    assert first.stats["characters_in"] == first.stats["characters_out"]


def test_what_is_not_content_is_removed_and_named():
    conversion = convert_html(
        "<p>Tekst.</p><script>alert(1)</script><style>p{}</style>"
        '<iframe src="https://video.example/1"></iframe><!-- uwaga --></b>'
        "<!DOCTYPE html><?php echo 1 ?><![CDATA[ukryte]]>"
        '<a href="/duze.jpg"><img src="https://cdn.example/a.jpg" alt="Pies"></a>'
        '<form><input name="q"><button>Szukaj</button></form>'
    )
    assert nodes(conversion) == [{"type": "paragraph", "content": [{"text": "Tekst."}]}]
    assert {(loss.severity, loss.kind, loss.detail) for loss in conversion.losses} == {
        (LOST, "tag_dropped", "script"),
        (LOST, "tag_dropped", "style"),
        (LOST, "tag_dropped", "iframe"),
        (LOST, "tag_dropped", "form"),
        (CHANGED, "comment_dropped", ""),
        (CHANGED, "declaration_dropped", ""),
        (CHANGED, "stray_end_tag", "b"),
        (LOST, "link_dropped", "link around an image"),
        (LOST, "image_dropped", "no media asset given"),
    }
    assert kinds(conversion)["declaration_dropped"] == 3


def test_markup_a_browser_forgives_is_read_as_a_browser_reads_it():
    conversion = convert_html(
        "<p>Pierwszy<p>Drugi<ul><li>raz<li>dwa</ul>"
        "<table><tr><td>a<td>b<tr><td>c<td>d</table><div>Luzem <b>w bloku</b></div>"
    )
    assert types(conversion) == ["core.rich_text", "core.table", "core.rich_text"]
    assert [node["type"] for node in nodes(conversion)] == ["paragraph", "paragraph", "list"]
    assert [len(row["cells"]) for row in conversion.blocks[1]["data"]["rows"]] == [2, 2]
    assert nodes(conversion, 2) == [
        {"type": "paragraph", "content": [{"text": "Luzem "}, {"text": "w bloku", "bold": True}]}
    ]
    assert conversion.losses == ()


def test_a_long_text_is_cut_at_a_heading_before_it_is_cut_anywhere():
    sections = "".join(
        f"<h2>Rozdział {chapter}</h2>" + "".join(f"<p>Akapit {n}.</p>" for n in range(49))
        for chapter in range(1, 8)
    )
    conversion = convert_html(sections)
    # 7 × 50 nodes: three chapters fit a block of 160, never a fourth.
    assert [len(block["data"]["content"]) for block in conversion.blocks] == [150, 150, 50]
    for block in conversion.blocks:
        assert block["data"]["content"][0]["type"] == "heading"
    assert [(loss.severity, loss.kind, loss.detail, loss.count) for loss in conversion.losses] == [
        (SPLIT, "rich_text_split", "before an h2", 2)
    ]
    # No heading to cut at: the limit itself.
    flat = convert_html("".join(f"<p>Akapit {n}.</p>" for n in range(170)))
    assert [len(block["data"]["content"]) for block in flat.blocks] == [160, 10]
    assert flat.losses[0].detail == "at the node limit"


def test_a_run_over_the_text_limit_is_cut_into_more_runs_not_shortened():
    conversion = convert_html(f"<p>{'ż' * 9000}</p>")
    assert [len(run["text"]) for run in nodes(conversion)[0]["content"]] == [4000, 4000, 1000]
    assert conversion.losses == ()


def test_every_block_is_valid_and_every_character_is_accounted_for():
    conversion = convert_html(
        TABLE + FAQ + "<h2>Dalej</h2><ol><li>raz</li></ol><blockquote>cytat</blockquote><hr>"
        "<pre>kod\n  wcięty</pre><dl><dt>Termin</dt><dd>Opis</dd></dl><p>&nbsp;</p>",
        image_assets={},
    )
    validators = site_block_contracts().validators
    for block in conversion.blocks:
        validator = validators[block["block_type"]][block["schema_version"]]
        assert list(validator.iter_errors(block["data"])) == []
    assert_unique_anchors(conversion.blocks)
    assert conversion.stats["characters_in"] == conversion.stats["characters_out"]
    assert "text_dropped" not in kinds(conversion)
    assert "text_mismatch" not in kinds(conversion)
    assert conversion.stats["blocks"] == {
        "core.rich_text": 4,
        "core.table": 1,
        "core.faq": 1,
        "core.separator": 1,
    }
    report = format_report(conversion)
    assert "blocks: core.rich_text ×1" not in report
    assert "core.table ×1" in report
    assert "0 lost" in report


# -- a table and a translation ----------------------------------------------


def test_a_table_s_caption_and_cells_are_the_text_units_of_a_language_version():
    table = convert_html(TABLE).blocks[1]
    units = {unit.key: unit for unit in extract_units([table])}
    assert units["0/caption"].kind == UNIT_TEXT
    assert units["0/caption"].text == "Porównanie ras"
    assert units["0/caption"].max_length == 300
    assert units["0/rows/0/cells/0/content"].kind == UNIT_INLINE
    assert units["0/rows/2/cells/1/content"].text == "mały, zob. ⟦1⟧opis⟦/1⟧"
    # An empty cell is no unit: a language version is never incomplete by it.
    assert "0/rows/2/cells/2/content" not in units
    assert "0/header" not in units
    assert len(units) == 1 + 15

    translated = assemble(
        [table],
        {
            "0/caption": "Breed comparison",
            "0/rows/0/cells/0/content": "Breed",
            "0/rows/2/cells/1/content": "small, see the ⟦1⟧description⟦/1⟧",
        },
    )
    data = translated.blocks[0]["data"]
    assert data["caption"] == "Breed comparison"
    assert data["rows"][0]["cells"][0] == {"content": [{"text": "Breed"}]}
    # The link keeps its target and its place in the grid.
    assert data["rows"][2]["cells"][1] == {
        "content": [
            {"text": "small, see the "},
            {"text": "description", "href": "/rasy/jamnik"},
        ]
    }
    assert data["rows"][2]["cells"][2] == {}
    assert data["header"] == "row"
    assert len(translated.missing) == 13


def test_a_link_an_automation_adds_to_a_table_cell_gets_its_default_rel():
    assert ("core.table", TABLE_VERSION) in REL_CAPABLE_BLOCKS


# -- the entry service takes it as it is --------------------------------------


@pytest.mark.django_db
def test_the_entry_service_stores_and_publishes_what_the_converter_made():
    from test_sites_api import create_site, csrf_value, sites_client
    from test_sites_collections import create_collection, create_entry, publish

    cache.clear()
    client, _organization, _user = sites_client(slug="html-import", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(client, collection.data["id"], slug="wpis", idempotency_key="html-entry")
    conversion = convert_html(TABLE + FAQ + "<hr><h2>Dalej</h2><ul><li>raz</li></ul>")
    assert set(types(conversion)) == {"core.rich_text", "core.table", "core.faq", "core.separator"}

    saved = client.put(
        f"/api/v1/sites/entries/{entry.data['id']}/draft/",
        {"expected_version": 0, "blocks": conversion.blocks},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="html-draft",
    )
    assert saved.status_code == 201, saved.content
    stored = saved.json()["blocks"]
    assert [block["block_type"] for block in stored] == types(conversion)
    assert [block["data"] for block in stored] == [block["data"] for block in conversion.blocks]
    published = publish(client, entry.data["id"], idempotency_key="html-publish")
    assert published.status_code in (200, 201), published.content


# -- the dry run ---------------------------------------------------------------


def test_the_command_prints_the_report_for_a_file_and_writes_nothing(tmp_path: Path):
    source = tmp_path / "wpis.html"
    source.write_text(TABLE + '<img src="https://cdn.example/a.jpg" alt="Pies">', encoding="utf-8")
    out = StringIO()
    call_command("sites_convert_html", str(source), stdout=out)
    report = out.getvalue()
    assert "blocks: core.rich_text ×1, core.table ×1, core.rich_text ×1" not in report
    assert "core.rich_text ×2, core.table ×1" in report
    assert "images: 1" in report
    assert "lost    image_dropped (no media asset given) ×1 — „https://cdn.example/a.jpg”" in report
    assert "changed table_span_flattened (2×1 cells) ×1" in report

    out = StringIO()
    call_command(
        "sites_convert_html",
        str(source),
        "--json",
        "--image",
        f"https://cdn.example/a.jpg={ASSET}",
        stdout=out,
    )
    result = json.loads(out.getvalue())
    assert result["images"] == ["https://cdn.example/a.jpg"]
    assert result["blocks"][-1]["data"]["content"][-1] == {
        "type": "figure",
        "image": {"asset_id": ASSET, "alt": "Pies"},
    }
    assert all(loss["severity"] != LOST for loss in result["losses"])

    with pytest.raises(CommandError):
        call_command("sites_convert_html", str(tmp_path / "brak.html"))
    with pytest.raises(CommandError):
        call_command("sites_convert_html", str(source), "--image", "bez-znaku-rownosci")
