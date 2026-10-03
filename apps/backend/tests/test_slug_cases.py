"""A language version's address comes out the same from the backend and from
the panel (ADR-070 pkt 18): both generators answer the shared cases in
`packages/contracts/locales/slug-cases.json`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.conf import settings

from saas_core.content_protocol.transliteration import slug_from_title

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
