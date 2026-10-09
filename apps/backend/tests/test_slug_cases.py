"""A language version's address comes out the same from the backend and from
the panel (ADR-070 pkt 18): both generators answer the shared cases in
`packages/contracts/locales/slug-cases.json`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.conf import settings

from saas_core.content_protocol.transliteration import following_slug, slug_from_title

CASES = json.loads(
    (
        Path(settings.BASE_DIR).parent.parent / "packages/contracts/locales/slug-cases.json"
    ).read_text(encoding="utf-8")
)["cases"]


@pytest.mark.parametrize(("title", "slug"), [(case["title"], case["slug"]) for case in CASES])
def test_a_title_gives_the_shared_address(title: str, slug: str) -> None:
    assert slug_from_title(title) == slug


def test_a_long_title_is_cut_on_a_word_without_a_trailing_hyphen() -> None:
    slug = slug_from_title("Strzyżenie " * 20, max_length=30)
    assert len(slug) <= 30 and not slug.endswith("-")


def test_an_apostrophe_is_dropped_and_the_earlier_spelling_is_still_told() -> None:
    """„Owner's” is one word in an address. Until 2026-10-09 the apostrophe
    broke it; that spelling is what stored addresses may still be, so the
    rule can still give it — and for a title without one both are the same."""
    assert slug_from_title("Dog Owner's Guide") == "dog-owners-guide"
    assert slug_from_title("Dog Owner\u2019s Guide") == "dog-owners-guide"
    assert slug_from_title("Dog Owner's Guide", apostrophes="-") == "dog-owner-s-guide"
    assert slug_from_title("Dog Owner\u2019s Guide", apostrophes="-") == "dog-owner-s-guide"
    for case in CASES:
        if not any(mark in case["title"] for mark in "'\u2019\u2018\u02bc"):
            assert slug_from_title(case["title"], apostrophes="-") == case["slug"]


def test_an_address_that_follows_its_title_does_not_move_because_the_rule_did() -> None:
    taken = {"dogs", "dog-owners-guide"}

    def free(base: str) -> str:
        slug, number = base, 2
        while slug in taken:
            slug, number = f"{base}-{number}", number + 1
        return slug

    # Made from this very title by the earlier rule: it stays, numbered or not.
    assert following_slug("Cat Owner's Guide", stored="cat-owner-s-guide", free=free) == (
        "cat-owner-s-guide"
    )
    taken.add("cat-owner-s-guide")
    assert following_slug("Cat Owner's Guide", stored="cat-owner-s-guide-2", free=free) == (
        "cat-owner-s-guide-2"
    )
    # A new title, or nothing stored yet, gets the rule of today.
    assert following_slug("Cat Owner's Handbook", stored="cat-owner-s-guide", free=free) == (
        "cat-owners-handbook"
    )
    assert following_slug("Bird Owner's Guide", stored="", free=free) == "bird-owners-guide"
    # Taken today: the first free one, as before.
    assert following_slug("Dog Owner's Guide", stored="", free=free) == "dog-owners-guide-2"
    # Without an apostrophe nothing is asked twice and nothing changes.
    asked: list[str] = []

    def counting(base: str) -> str:
        asked.append(base)
        return free(base)

    assert following_slug("Dogs", stored="dogs-2", free=counting) == "dogs-2"
    assert asked == ["dogs"]
    # A title that gives no address falls back, as each caller did before.
    assert following_slug(" — ", stored="", free=free, fallback="about") == "about"
