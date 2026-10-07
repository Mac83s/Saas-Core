"""HTML → core blocks with a loss report (plan PB2,
`docs/architecture/site-html-import.md`): what each construct becomes, that
nothing goes missing without being named, that the limits split instead of
cutting, and that the result is what the entry service and a translation take
as they are."""

from __future__ import annotations

import json
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


def test_a_heading_too_long_for_one_or_holding_a_link_says_so():
    long = "Bardzo długi śródtytuł " * 12
    conversion = convert_html(f'<h2>{long}</h2><h3><a href="/x">Z linkiem</a></h3>')
    assert nodes(conversion)[0] == {
        "type": "paragraph",
        "content": [{"text": long.strip(), "bold": True}],
    }
    assert nodes(conversion)[1]["text"] == "Z linkiem"
    assert kinds(conversion) == {"link_dropped": 1, "heading_too_long": 1}


def test_an_underline_is_removed_and_a_bold_underlined_paragraph_is_a_sub_heading():
    conversion = convert_html(
        "<p><b><u>Wygląd ogólny</u></b></p>"
        "<p><u><strong>Charakter</strong></u><br>Pies <u>spokojny</u> i czujny.</p>"
        "<ul><li><b><u>Waga:</u></b> 30 kg</li></ul>"
        '<p><span style="text-decoration: underline">Podkreślone stylem</span></p>'
    )
    assert nodes(conversion) == [
        {"type": "heading", "level": 3, "anchor": "wyglad-ogolny", "text": "Wygląd ogólny"},
        {"type": "heading", "level": 3, "anchor": "charakter", "text": "Charakter"},
        {"type": "paragraph", "content": [{"text": "Pies spokojny i czujny."}]},
        {
            "type": "list",
            "style": "bullet",
            "items": [{"content": [{"text": "Waga:", "bold": True}, {"text": " 30 kg"}]}],
        },
        {"type": "paragraph", "content": [{"text": "Podkreślone stylem"}]},
    ]
    assert kinds(conversion) == {
        "underline_bold_as_heading": 2,
        "underline_dropped": 3,
        "line_break_as_paragraph": 1,
    }
    assert conversion.count(LOST) == 0


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


def test_words_in_a_place_a_table_has_no_cell_for_are_named_as_lost():
    conversion = convert_html("<table>luzem<tr>w wierszu<td>komórka</td></tr></table>")
    assert conversion.blocks[0]["data"]["rows"] == [{"cells": [{"content": [{"text": "komórka"}]}]}]
    assert [(loss.severity, loss.kind, loss.detail) for loss in conversion.losses] == [
        (LOST, "text_dropped", "inside <table>"),
        (LOST, "text_dropped", "inside <tr>"),
    ]


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
        '<form><input name="q"><button>Szukaj</button></form>'
    )
    assert nodes(conversion) == [{"type": "paragraph", "content": [{"text": "Tekst."}]}]
    assert {(loss.severity, loss.kind, loss.detail) for loss in conversion.losses} == {
        (LOST, "tag_dropped", "script"),
        (LOST, "tag_dropped", "style"),
        (LOST, "tag_dropped", "iframe"),
        (LOST, "tag_dropped", "form"),
        (CHANGED, "comment_dropped", ""),
        (CHANGED, "stray_end_tag", "b"),
    }


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
