"""People in a command's answer (ADR-076, uzupełnienie 2026-10-04 „karty osób”).

A command's output goes to a model, so it never carries somebody's name,
e-mail or phone. Where the answer means a person, the command writes a handle
— `klient:k7m2q` — and whoever runs the plan keeps the book of which record
each handle stands for: the assistant keeps it with its conversation. The
person at the screen reads a card instead, made by the module that owns the
record from the record as it is now, under that reader's own permissions.

A handle is derived from the conversation and the record, not counted: the
same person has the same handle wherever a conversation meets them, another
conversation has another one for them, and a handle somebody makes up stands
for nobody. Only a handle in the caller's book resolves — so a command that
takes one (`resolve_person`) refuses a handle of another conversation, of
another company, or a guessed one, with the field it came in.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured
from django.utils.crypto import salted_hmac
from rest_framework.exceptions import ErrorDetail, ValidationError

from .context import require_tenant_context

_PREFIX = re.compile(r"^[a-z]{2,20}$")
_SHORTEST = 5

#: handle → (kind, the record's id)
type Book = dict[str, tuple[str, UUID]]
#: The record's ids → what the reader may see of each: `name`, `email`,
#: `phone` (a value, or None for what they may not see or there is none of)
#: and `links` (`{"title": {pl, en}, "href"}` into the panel).
type Cards = Callable[[Sequence[UUID]], Mapping[UUID, Mapping[str, Any]]]


@dataclass(frozen=True, slots=True)
class PersonKind:
    kind: str
    #: The word a handle of this kind starts with.
    prefix: str
    cards: Cards


class PersonHandleUnknown(ValidationError):
    problem_code = "person_handle_unknown"


_kinds: dict[str, PersonKind] = {}
_book: ContextVar[Book | None] = ContextVar("command_people", default=None)


def register_person_kind(kind: PersonKind) -> None:
    """From the `AppConfig.ready` of the module that owns the record."""
    if not _PREFIX.fullmatch(kind.prefix):
        raise ImproperlyConfigured(f"Rodzaj osoby {kind.kind}: przedrostek to małe litery.")
    for other in _kinds.values():
        if other.kind != kind.kind and other.prefix == kind.prefix:
            raise ImproperlyConfigured(f"Przedrostek {kind.prefix} ma już {other.kind}.")
    _kinds[kind.kind] = kind


@contextmanager
def known_people(book: Book) -> Iterator[Book]:
    """Runs commands with the caller's book: handles in it resolve, and every
    handle a command issues meanwhile is added to it — for the caller to keep."""
    token = _book.set(book)
    try:
        yield book
    finally:
        _book.reset(token)


def person_handle(kind: str, subject_id: UUID) -> str:
    """The handle a command writes where its answer means this person."""
    context = require_tenant_context()
    # The conversation a command runs for; a person acting directly has only
    # their membership, and nobody keeps a book for them.
    scope = context.acting_ref or f"membership:{context.membership_id}"
    digest = salted_hmac(
        "core.commands.people", f"{context.organization_id}:{scope}:{kind}:{subject_id}"
    ).digest()
    code = base64.b32encode(digest).decode().lower().rstrip("=")
    prefix = _kinds[kind].prefix
    book = _book.get()
    entry = (kind, subject_id)
    for length in range(_SHORTEST, len(code) + 1):
        handle = f"{prefix}:{code[:length]}"
        # Two people whose handles begin alike: the later one gets a longer one.
        if book is None or book.get(handle, entry) == entry:
            break
    if book is not None:
        book[handle] = entry
    return handle


def resolve_person(kind: str, handle: str, *, field: str) -> UUID:
    """The record a handle stands for — in the caller's own book only."""
    found = (_book.get() or {}).get(handle)
    if found is None or found[0] != kind:
        raise PersonHandleUnknown({
            field: [
                ErrorDetail(
                    "Ten identyfikator osoby nie pochodzi z tej rozmowy.",
                    code="person_handle_unknown",
                )
            ]
        })
    return found[1]


def handles_in(text: str, book: Iterable[str]) -> list[str]:
    """The handles of a book that a text names, in the order it names them.

    Looked for one by one, not by what a handle looks like: a model writes a
    colon, a bracket or a comma straight after one („- klient:k7m2q: pasuje
    nazwisko”), and a card must not depend on its punctuation. A handle
    followed by more letters or digits is another word."""
    found = []
    for handle in book:
        match = re.search(rf"(?<!\w){re.escape(handle)}(?![A-Za-z0-9])", text)
        if match is not None:
            found.append((match.start(), handle))
    return [handle for _at, handle in sorted(found)]


def person_cards(people: Mapping[str, tuple[str, UUID]]) -> dict[str, dict[str, Any]]:
    """Each handle's card as the caller may read it now. A person the caller
    may not see — or whose record is gone, or whose kind no module of this
    deployment owns — has an empty card: the handle still stands for somebody,
    and the panel says so instead of showing the handle."""
    cards: dict[str, dict[str, Any]] = {
        handle: {
            "handle": handle,
            "kind": kind,
            "name": None,
            "email": None,
            "phone": None,
            "links": [],
        }
        for handle, (kind, _subject_id) in people.items()
    }
    by_kind: dict[str, dict[UUID, list[str]]] = {}
    for handle, (kind, subject_id) in people.items():
        by_kind.setdefault(kind, {}).setdefault(subject_id, []).append(handle)
    for kind, subjects in by_kind.items():
        declared = _kinds.get(kind)
        if declared is None:
            continue
        for subject_id, card in declared.cards(list(subjects)).items():
            for handle in subjects.get(subject_id, ()):
                cards[handle].update(card)
    return cards
