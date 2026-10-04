"""Every message template the panel lists has a name, a line on its use and
words for its variables, in Polish and English (UX-048, R13): the panel shows
„Szablon bez nazwy” rather than a key, and this keeps it from having to.

Core's and shared modules' templates are named in the core messages; a
product's own are named in the product's messages and checked there.
"""

from __future__ import annotations

import json
from pathlib import Path

from saas_core.modules.shared.notifications.templates import TEMPLATES

MESSAGES = Path(__file__).resolve().parents[2] / "frontend" / "messages"
#: Namespaces of core and shared modules; anything else is a product's.
CORE_PREFIXES = (
    "billing.",
    "booking.",
    "commerce.",
    "inventory.",
    "product.",
    "sites.",
    "system.",
    "translation.",
)


def test_every_core_template_has_its_words_in_both_languages() -> None:
    templates = [
        template for (key, _), template in TEMPLATES.items() if key.startswith(CORE_PREFIXES)
    ]
    assert templates
    for locale in ("pl", "en"):
        words = json.loads((MESSAGES / f"{locale}.json").read_text(encoding="utf-8"))[
            "Notifications"
        ]
        slugs = {template.key.replace(".", "_") for template in templates}
        fields = {field for template in templates for field in template.allowed_context}
        assert not sorted(slugs - set(words["templateNames"])), (
            f"Notifications.templateNames ({locale}) nie nazywa: "
            f"{sorted(slugs - set(words['templateNames']))}"
        )
        assert not sorted(slugs - set(words["templateUse"])), (
            f"Notifications.templateUse ({locale}) nie opisuje: "
            f"{sorted(slugs - set(words['templateUse']))}"
        )
        assert not sorted(fields - set(words["variables"])), (
            f"Notifications.variables ({locale}) nie nazywa: "
            f"{sorted(fields - set(words['variables']))}"
        )
