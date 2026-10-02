"""What a page's draft still says only to its owner (UX-038): the template's
`[Uzupełnij: …]` slots and its sample phone or e-mail.

A page built from a template is published the moment it reads well enough,
and the visitor would then see „[Uzupełnij: obszar dojazdu]” or call
+48 000 000 000. The publication's readiness names both before that happens.
The slots are found the way a language version finds them (`extract_units`,
`PLACEHOLDER_PATTERN`), so readiness and the language gate count the same.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from saas_core.content_protocol.tokens import PLACEHOLDER_PATTERN

from .block_decoration import stored_block_payload
from .localized_bodies import extract_units
from .models import Page, PageBlock

#: The templates' sample contact: a number of zeros, an example.* address.
TEMPLATE_PHONE = re.compile(r"^tel:(\+\d{2})?0{9,}$")
TEMPLATE_EMAIL = re.compile(r"^mailto:[^@]+@example\.(com|org|net)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PageContent:
    #: `[Uzupełnij: …]` slots left in the page's draft.
    placeholders: int
    #: The template's phone or e-mail still in a link of the draft.
    template_contact: bool


def is_template_contact(href: str) -> bool:
    href = href.strip()
    return bool(TEMPLATE_PHONE.match(href.replace(" ", "")) or TEMPLATE_EMAIL.match(href))


def _hrefs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "href" and isinstance(item, str):
                yield item
            else:
                yield from _hrefs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _hrefs(item)


def page_content(organization_id: UUID, pages: Sequence[Page]) -> dict[UUID, PageContent]:
    """Each page's current draft, one query for the site."""
    drafts = {page.current_draft_id: page.id for page in pages if page.current_draft_id}
    by_page: dict[UUID, list[Any]] = {}
    for block in PageBlock.all_objects.filter(
        organization_id=organization_id, page_version_id__in=list(drafts)
    ).order_by("page_version_id", "position"):
        by_page.setdefault(drafts[block.page_version_id], []).append(block)
    report: dict[UUID, PageContent] = {}
    for page_id, blocks in by_page.items():
        units = extract_units([stored_block_payload(block) for block in blocks])
        report[page_id] = PageContent(
            placeholders=sum(len(PLACEHOLDER_PATTERN.findall(unit.text)) for unit in units),
            template_contact=any(
                is_template_contact(href) for block in blocks for href in _hrefs(block.data)
            ),
        )
    return report


#: The company's own phone and e-mail as its business card shows them, ("", "")
#: when it shows none. Profiles registers it: sites does not depend on them.
ContactSource = Callable[[UUID], tuple[str, str]]
_contact_source: list[ContactSource] = []


def register_company_contact(source: ContactSource) -> None:
    _contact_source[:] = [source]


def company_contact(organization_id: UUID) -> tuple[str, str]:
    return _contact_source[0](organization_id) if _contact_source else ("", "")


def with_company_contact(
    blocks: list[dict[str, Any]], phone: str, email: str
) -> list[dict[str, Any]]:
    """A template's sample phone and e-mail replaced by the company's own
    (UX-038); a link the company has nothing for keeps the sample, which the
    readiness card then names."""
    number = re.sub(r"[^\d+]", "", phone)

    def fill(value: Any) -> Any:
        if isinstance(value, dict):
            href = value.get("href")
            if isinstance(href, str) and is_template_contact(href):
                if href.startswith("tel:") and number:
                    return {**value, "href": f"tel:{number}"}
                if href.startswith("mailto:") and email:
                    return {**value, "href": f"mailto:{email}"}
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        return value

    return [fill(block) for block in blocks]
