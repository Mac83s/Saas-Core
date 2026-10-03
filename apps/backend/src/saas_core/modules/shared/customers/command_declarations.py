"""The assistant's commands for the company's documents for customers
(ADR-076 §1; ADR-073 §9, phase 4d).

Thin adapters over the services the panel's „Dokumenty dla klientów” calls.
The assistant reads the documents and writes a draft, marked with the
conversation that wrote it (`origin_ref`). A draft binds nobody: what
customers read and agree to is a version, and approving one stays a person's
alone — with a fresh second factor, in the panel. There is no command for it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from saas_core.modules.core.organizations.api import CommandSpec, Effect, Preview, register_command
from saas_core.modules.core.organizations.models import Organization

from .documents import (
    CUSTOMERS_MANAGE,
    CUSTOMERS_READ,
    DOCUMENT_TEXT_MAX,
    document_options,
    list_documents,
    plan_draft,
    read_document,
    save_draft,
)
from .models import DocumentKind

_KINDS = list(DocumentKind.values)
_LABELS = {
    DocumentKind.BOOKING_TERMS: ("Regulamin rezerwacji", "Booking terms"),
    DocumentKind.SHOP_TERMS: ("Regulamin sklepu", "Shop terms"),
    DocumentKind.PRIVACY_POLICY: ("Polityka prywatności", "Privacy policy"),
    DocumentKind.CANCELLATION_POLICY: ("Polityka anulowania", "Cancellation policy"),
}

_VERSION = {
    "type": ["object", "null"],
    "properties": {
        "number": {"type": "integer"},
        "source_locale": {"type": "string"},
        "effective_from": {"type": "string"},
        "locales": {"type": "array"},
        # The current text per language; only when one document is asked for.
        "texts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"locale": {"type": "string"}, "text": {"type": "string"}},
            },
        },
    },
}
_DOCUMENT = {
    "type": "object",
    "properties": {
        "kind": {"type": "string"},
        "version": {"type": "integer"},
        "draft": {
            "type": ["object", "null"],
            "properties": {
                "text": {"type": "string"},
                "locale": {"type": "string"},
                "origin_ref": {"type": "string"},
            },
        },
        "in_force": _VERSION,
        "upcoming": _VERSION,
        "public_url": {"type": ["string", "null"]},
    },
}
#: What the company publishes for everybody, and the draft of it: its own
#: text, with nobody's personal data — who approved a version is left out.
_DOCUMENTS = {
    "type": "object",
    "x-data-class": "public",
    "properties": {
        "documents": {"type": "array", "items": _DOCUMENT},
        "locales": {"type": "array"},
        "default_locale": {"type": "string"},
        "text_max": {"type": "integer"},
    },
}


def _version(version: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if version is None:
        return None
    shown: dict[str, Any] = {
        "number": version["number"],
        "source_locale": version["source_locale"],
        "effective_from": str(version["effective_from"]),
        "locales": list(version["locales"]),
    }
    if "texts" in version:
        shown["texts"] = [
            {"locale": row["locale"], "text": row["text"]} for row in version["texts"]
        ]
    return shown


def _document(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "kind": document["kind"],
        "version": document["version"],
        "draft": dict(document["draft"]) if document["draft"] else None,
        "in_force": _version(document["in_force"]),
        "upcoming": _version(document["upcoming"]),
        "public_url": document["public_url"],
    }


def _answer(documents: list[Mapping[str, Any]], options: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "documents": [_document(document) for document in documents],
        "locales": list(options["locales"]),
        "default_locale": options["default_locale"],
        "text_max": options["text_max"],
    }


def _read(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    if arguments["kind"] is None:
        listed = list_documents()
        return _answer(listed["documents"], listed["options"])
    one = read_document(arguments["kind"])
    return _answer([one["document"]], one["options"])


def _resource(call: Any, kind: str) -> str:
    return f"customers.document:{call.context.organization_id}:{kind}"


def _preview_draft(arguments: Mapping[str, Any], call: Any) -> Preview:
    kind = arguments["kind"]
    planned = plan_draft(kind, text=arguments["text"], locale=arguments["locale"])
    names = _LABELS[kind]
    binds = (
        (
            f" Klienci dalej czytają wersję {planned.in_force}.",
            f" Customers keep reading version {planned.in_force}.",
        )
        if planned.in_force
        else (
            " Dokument nie ma jeszcze zatwierdzonej wersji.",
            " The document has no approved version yet.",
        )
    )
    observed = {_resource(call, kind): planned.version}
    if not planned.changes:
        # The draft is already this text: the save would write nothing.
        return Preview(effects=(), observed_versions=observed)
    if not planned.text:
        kind_of_effect = "deleted"
        summary = {
            "pl": f"Szkic dokumentu „{names[0]}” zostanie usunięty.{binds[0]}",
            "en": f"The draft of “{names[1]}” will be removed.{binds[1]}",
        }
    else:
        kind_of_effect = "updated" if planned.replaces else "created"
        replaced = (
            (
                f" Zastąpi obecny szkic ({planned.replaces} znaków).",
                f" It replaces the current draft ({planned.replaces} characters).",
            )
            if planned.replaces
            else ("", "")
        )
        summary = {
            "pl": f"Szkic dokumentu „{names[0]}” w języku {planned.locale}: "
            f"{len(planned.text)} znaków.{replaced[0]} Szkic nikogo nie wiąże — wersję "
            f"zatwierdza osoba w panelu.{binds[0]}",
            "en": f"A draft of “{names[1]}” in {planned.locale}: {len(planned.text)} "
            f"characters.{replaced[1]} A draft binds nobody — a person approves a version "
            f"in the panel.{binds[1]}",
        }
    return Preview(
        effects=(
            Effect(
                kind=kind_of_effect,
                resource="customers.document_draft",
                resource_id=planned.document_id,
                summary=summary,
            ),
        ),
        observed_versions=observed,
    )


def _save_draft(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    kind = arguments["kind"]
    context = call.context
    saved = save_draft(
        kind,
        text=arguments["text"],
        locale=arguments["locale"],
        expected_version=call.preview.observed_versions[_resource(call, kind)],
        # The conversation that wrote it, shown beside the draft in the panel.
        origin_ref=context.acting_ref if context.acting_via == "assistant" else "",
    )
    # Not `read_document`: whoever may write a draft is not asked for the
    # right to read once more.
    organization = Organization.objects.get(pk=context.organization_id)
    return _answer([saved], document_options(organization))


_KIND_WORDS = (
    "booking_terms (the terms of booking), shop_terms (the shop's terms), privacy_policy "
    "(the privacy policy), cancellation_policy (the cancellation policy)"
)

DOCUMENTS_READ = CommandSpec(
    name="customers.documents.read",
    version=1,
    module="shared.customers",
    title={"pl": "Odczytaj dokumenty dla klientów", "en": "Read the documents for customers"},
    summary={
        "pl": "Regulaminy i polityki firmy: szkic, wersja obowiązująca i języki, w których "
        "ma tekst.",
        "en": "The company's terms and policies: the draft, the version in force and the "
        "languages it has a text in.",
    },
    model_description=(
        "Returns the company's documents for its customers — " + _KIND_WORDS + ". For each: "
        "its lock (`version`), the draft somebody is still writing (text, language and the "
        "conversation that wrote it, if any), the version in force today and the one waiting "
        "for its day (number, the language it was approved in, the day it applies from, the "
        "languages it has a text in), and the public address. With `kind` null every document "
        "comes without texts; with a kind, that one document comes with the current text of "
        "each language. Also the company's languages and the longest text allowed. A customer "
        "who reads a language the version has no text in gets no document. Use it before "
        "writing a draft."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["kind"],
        "properties": {
            "kind": {
                "type": ["string", "null"],
                "enum": [*_KINDS, None],
                "description": "One document with its texts, or null for all of them "
                "without texts.",
            },
        },
    },
    output_schema=_DOCUMENTS,
    permission=CUSTOMERS_READ,
    risk="read",
    run=_read,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)

DRAFT_SAVE = CommandSpec(
    name="customers.document.draft.save",
    version=1,
    module="shared.customers",
    title={"pl": "Zapisz szkic dokumentu dla klientów", "en": "Save a draft of a document"},
    summary={
        "pl": "Szkic regulaminu albo polityki; nikogo nie wiąże, wersję zatwierdza osoba.",
        "en": "A draft of terms or a policy; it binds nobody, a person approves a version.",
    },
    model_description=(
        "Writes the draft of one of the company's documents for its customers — "
        + _KIND_WORDS
        + " — replacing the draft it has; an empty text removes the draft. The text is plain "
        f"paragraphs separated by empty lines, no markup, at most {DOCUMENT_TEXT_MAX} "
        "characters, written in one of the company's languages (`locale`). A draft binds "
        "nobody: customers keep reading the version in force. Only a person can approve the "
        "draft as a version, in the panel, with a code from their authenticator app — never "
        "say a document is in force after saving a draft. A legal text you draft is a "
        "starting point the company should have checked."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "text", "locale"],
        "properties": {
            "kind": {
                "type": "string",
                "enum": _KINDS,
                "description": "Which document the draft belongs to.",
            },
            "text": {
                "type": "string",
                "description": "The whole draft: plain paragraphs separated by empty lines. "
                "An empty string removes the draft.",
            },
            "locale": {
                "type": "string",
                "description": "The language the draft is written in: two lowercase letters, "
                "one of the company's languages from customers.documents.read.",
            },
        },
    },
    output_schema=_DOCUMENTS,
    permission=CUSTOMERS_MANAGE,
    risk="draft",
    run=_save_draft,
    undo="command:customers.document.draft.save@1",
    preview=_preview_draft,
    version_field="expected_version",
)


def register_customer_commands() -> None:
    for spec in (DOCUMENTS_READ, DRAFT_SAVE):
        register_command(spec)
