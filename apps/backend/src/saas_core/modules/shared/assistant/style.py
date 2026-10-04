"""The one rule of style the server checks itself (ADR-076, uzupełnienie 2026-10-04 L3).

The assistant has no gender, and Polish shows one in two verb forms: the
first-person past tense („zmieniłem”, „pominąłem”) and the conditional
(„chciałbym”, „żebym pokazał”). The prompt forbids both and a model still
writes one in about one answer of ten, so an answer that has one is sent back
once, with the form named, before the person sees it. The same pattern grades
the evals: what the check lets through, the eval counts.

The pattern is wide on purpose (04.10: a browser walk-through read „Tej nie
zmieniałem”, which a list of verb stems did not hold): any word that ends like
such a verb, less the nouns and present-tense verbs that end the same way. A
noun it takes for a verb costs one more call of the model, not a wrong answer.
"""

from __future__ import annotations

import re

from saas_core.modules.shared.model_port.api import Message, ModelResponse

#: Nouns whose instrumental ends like a masculine verb („z działem”, „z Michałem”).
_NOUNS = (
    "kanałem|materiałem|działem|oddziałem|udziałem|podziałem|przedziałem|rozdziałem|wydziałem|"
    "przydziałem|sygnałem|kapitałem|potencjałem|oryginałem|finałem|ideałem|kawałem|wałem|"
    "zawałem|ciałem|upałem|zapałem|szałem|banałem|generałem|kardynałem|kryształem|minerałem|"
    "rytuałem|pedałem|trybunałem|arsenałem|kwartałem|interwałem|strzałem|morałem|futerałem|"
    "specjałem|pyłem|tyłem|michałem|rafałem|bogumiłem"
)
#: The present tense of „działać”, „wysyłać” and „pałać” ends like a feminine past.
_PRESENT = (
    "(?:za|z|po|od|przeciw|współ)?działam|(?:wy|prze|od|roz|na|ze|z|do|pod|za|po|nad)syłam|"
    "(?:za)?pałam"
)
#: Verbs whose past has a consonant before the ending: named one by one, because a
#: noun ends the same way („hasłem”, „pomysłem”, „źródłem”).
_STEMS = "mog|szed|znalaz|nios|wioz|bieg|piek|kład|siad|jad"
GENDERED = re.compile(
    # „zmieniłem”, „zmieniałem”, „pominąłem”, „użyłem”, „byłem”: by the vowel before the
    # ending — „zespołem”, „tytułem” and „ogółem” have another.
    rf"\b(?!(?:{_NOUNS})\b)\w+[aiyą]łem\b"
    rf"|\b\w*(?:{_STEMS})łem\b"
    # „zmieniłam”, „zmieniałam”, „pominęłam”, „mogłam”, „poszłam”.
    rf"|\b(?!(?:{_PRESENT})\b)\w+[aiyę]łam\b"
    rf"|\b\w*(?:{_STEMS}|sz)łam\b"
    # „chciałbym”, „mogłabym”: the conditional has a gender too — also when it
    # is split („żebym to zrobił”).
    r"|\b\w+ł[ao]?bym\b"
    r"|\b(?:że|a|gdy|o)bym\b[^.?!\n]{0,40}?\b\w+ła?\b"
    # „będę sprawdzał”, „powinienem”, „powinnam”.
    r"|\bbędę\s+(?:\w+\s+)?\w+ła?\b"
    r"|\bpowin(?:ienem|nam)\b",
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
