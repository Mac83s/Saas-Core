"""The structured data of one public page: a single JSON-LD graph (ADR-071
pkt 16, plan TL18).

Built from what the visitor gets — the page payload and the facts the
publication froze — so the graph, the head and the sitemap cannot disagree.
The company is one node, `#organization`, with the same `@id` and the same
facts under every language; pages and articles point at it and say their own
language. The renderer only prints the result (`#lib/seo` escapes it).
"""

from __future__ import annotations

from typing import Any

CONTEXT = "https://schema.org"
FAQ_BLOCK = "core.faq"


def organization_id(origin: str) -> str:
    """One identity per site, in every language; the catalogue card names the
    same node (`catalogCardJsonLd`)."""
    return f"{origin}/#organization"


def website_id(origin: str) -> str:
    return f"{origin}/#website"


def organization_node(
    *, origin: str, site_name: str, facts: dict[str, Any] | None
) -> dict[str, Any]:
    """The company as its business card stated it when the site was published.

    `LocalBusiness` when the card has an address, with the category's subtype
    beside it when it names one; otherwise `Organization`. A site published
    before the facts were frozen, or by a company without a card, is known by
    the site's name alone.
    """
    facts = facts or {}
    node: dict[str, Any] = {
        "@type": "Organization",
        "@id": organization_id(origin),
        "name": str(facts.get("name") or site_name),
        "url": f"{origin}/",
    }
    street = str(facts.get("street_address") or "")
    if street:
        subtype = str(facts.get("business_type") or "")
        node["@type"] = ["LocalBusiness", subtype] if subtype else "LocalBusiness"
    address = {
        key: str(facts[field])
        for key, field in (
            ("streetAddress", "street_address"),
            ("addressLocality", "locality"),
            ("addressRegion", "region"),
            ("addressCountry", "country"),
        )
        if facts.get(field)
    }
    if address:
        node["address"] = {"@type": "PostalAddress", **address}
    for key, field in (("telephone", "telephone"), ("email", "email")):
        if facts.get(field):
            node[key] = str(facts[field])
    same_as = [str(url) for url in facts.get("same_as") or () if url]
    if same_as:
        node["sameAs"] = same_as
    return node


def _faq(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The questions the page answers in its FAQ blocks, as it shows them."""
    questions: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("block_type") != FAQ_BLOCK:
            continue
        for item in (block.get("data") or {}).get("items") or ():
            if not isinstance(item, dict):
                continue
            question, answer = str(item.get("question") or ""), str(item.get("answer") or "")
            if question.strip() and answer.strip():
                questions.append({
                    "@type": "Question",
                    "name": question.strip(),
                    "acceptedAnswer": {"@type": "Answer", "text": answer.strip()},
                })
    return questions


def page_graph(
    *,
    origin: str,
    site_name: str,
    locale: str,
    canonical_url: str,
    title: str,
    description: str,
    breadcrumbs: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
    article: dict[str, Any] | None,
    image: dict[str, str] | None,
    facts: dict[str, Any] | None,
) -> dict[str, Any]:
    """WebSite, the company, this page, its trail, and what the page is
    besides: an article (`BlogPosting`) or a page of questions (`FAQPage`)."""
    organization = {"@id": organization_id(origin)}
    website = {"@id": website_id(origin)}
    page_id = f"{canonical_url}#webpage"
    questions = _faq(blocks)
    page: dict[str, Any] = {
        "@type": ["WebPage", "FAQPage"] if questions else "WebPage",
        "@id": page_id,
        "url": canonical_url,
        "name": title,
        "inLanguage": locale,
        "isPartOf": website,
        "about": organization,
    }
    if description:
        page["description"] = description
    if image:
        page["primaryImageOfPage"] = {"@type": "ImageObject", "url": image["url"]}
    if questions:
        page["mainEntity"] = questions
    graph: list[dict[str, Any]] = [
        {
            "@type": "WebSite",
            "@id": website["@id"],
            "url": f"{origin}/",
            "name": site_name,
            "publisher": organization,
        },
        organization_node(origin=origin, site_name=site_name, facts=facts),
        page,
    ]
    if breadcrumbs:
        page["breadcrumb"] = {"@id": f"{canonical_url}#breadcrumb"}
        graph.append({
            "@type": "BreadcrumbList",
            "@id": f"{canonical_url}#breadcrumb",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": position,
                    "name": str(crumb["title"]),
                    "item": f"{origin}{crumb['path']}",
                }
                for position, crumb in enumerate(breadcrumbs, start=1)
            ],
        })
    if article is not None:
        author = str(article.get("author_name") or "").strip()
        posting: dict[str, Any] = {
            "@type": "BlogPosting",
            "@id": f"{canonical_url}#article",
            # The entry's own title where the payload carries it (K2's byline
            # shows that one); the page's title is the same text until then.
            "headline": str(article.get("title") or title),
            "inLanguage": locale,
            "mainEntityOfPage": {"@id": page_id},
            "isPartOf": website,
            # An article nobody signed is the company's own.
            "author": {"@type": "Person", "name": author} if author else organization,
            "publisher": organization,
        }
        if description:
            posting["description"] = description
        # The same moments the visitor reads, the sitemap's `lastmod` and
        # `article:modified_time` carry (TL14).
        if article.get("published_at"):
            posting["datePublished"] = str(article["published_at"])
        if article.get("updated_at"):
            posting["dateModified"] = str(article["updated_at"])
        if image:
            posting["image"] = image["url"]
        keywords = [str(tag["name"]) for tag in article.get("tags") or () if tag.get("name")]
        if keywords:
            posting["keywords"] = keywords
        graph.append(posting)
    return {"@context": CONTEXT, "@graph": graph}
