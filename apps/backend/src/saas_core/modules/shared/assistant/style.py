"""The one rule of style the server checks itself (ADR-076, uzupełnienie 2026-10-04 L3).

The assistant has no gender, and Polish shows one in two verb forms: the
first-person past tense („zmieniłem”, „pominąłem”) and the conditional
(„chciałbym”, „żebym pokazał”). The prompt forbids both and a model still
writes one in about one answer of ten, so an answer that has one is sent back
once, with the form named, before the person sees it. The same pattern grades
the evals: what the check lets through, the eval counts.
"""

from __future__ import annotations

import re

from saas_core.modules.shared.model_port.api import Message, ModelResponse

# By verb, because a noun ends the same way („zespołem”, „tytułem”).
GENDERED = re.compile(
    r"\b(?:\w*(?:zmieni|stawi|doda|robi|sprawdzi|pisa|usun[ąę]|kona|znalaz|tworzy|"
    r"owa|wysła|czyta|prawi|łączy|wybra|mog|musia|chcia|by|pomin[ąę]|stali|wprowadzi))"
    r"(?:łem|łam)\b"
    # „chciałbym”, „mogłabym”: the conditional has a gender too — also when it
    # is split („żebym to zrobił”).
    r"|\b\w+ł[ao]?bym\b"
    r"|\b(?:że|a|gdy|o)bym\b[^.?!\n]{0,40}?\b\w+ła?\b",
    re.IGNORECASE,
)


def gendered(text: str) -> str:
    """The first verb form with a gender in the text, or an empty string."""
    found = GENDERED.search(text)
    return found.group(0) if found else ""


def rewrite_messages(response: ModelResponse, form: str) -> tuple[Message, Message]:
    """What goes after the transcript to have the answer written again: the
    answer itself and the panel's note about it. Neither is kept — the person
    reads only the answer that comes back."""
    note = (
        "[panel] This is not the person: your last answer was held back because it uses a "
        f'Polish verb form that has a gender ("{form}"). Write the same answer again, in the '
        "same language, without any first-person past tense and without a conditional that "
        'has a gender: impersonal forms ("Gotowe", "Zmieniono", "Pominięto") or the present '
        'tense ("Pomijam", "Mogę pokazać", "żeby pokazać"). Change nothing else, call no '
        "tool, and do not mention this note."
    )
    return response.as_message(), Message(role="user", content=note)
