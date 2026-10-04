"""Public use-case API of the Customers module (ADR-073 §2).

A company's end customer is one record for bookings, orders and the shop.
Another module reaches it through this file: `CUSTOMER_MODEL` for its own
foreign key, `match_or_create` on a first booking or order, and
`register_customer_anonymizer` for what it stores about a customer beside the
customer's row — with `keeps` when it must leave something for a time, read
back by `kept_after_strip` — and `CUSTOMER_RETENTION_SWEEP` for the key under
which it holds a customer back from the company's removal after a time.

The company's documents for its customers (§9) are read and agreed to through
two calls, both made inside the tenant the caller already holds — a public
form's service context is enough: `current_document(kind, locale)` gives the
text in force in exactly that language (or None — never another language),
and `record_consent(...)` appends who saw which text row to the journal;
`consents_of(source, references)` reads the lines written for a source's
records back, for the screen that shows the record. `document_locales(kind)`
says which languages the document in force has, and `marketing_wording`
(over `MARKETING_WORDING`) is the one sentence of a marketing consent.
"""

from .documents import (
    MARKETING_WORDING,
    DocumentInForce,
    consents_of,
    current_document,
    document_locales,
    marketing_wording,
    record_consent,
)
from .models import ConsentKind, Customer, DocumentKind
from .services import (
    CUSTOMER_RETENTION_SWEEP,
    CustomerAnonymizer,
    Kept,
    kept_after_strip,
    match_or_create,
    register_customer_anonymizer,
    strip_customer,
)

CUSTOMER_MODEL = "customers.Customer"

__all__ = [
    "CUSTOMER_MODEL",
    "MARKETING_WORDING",
    "CUSTOMER_RETENTION_SWEEP",
    "ConsentKind",
    "Customer",
    "CustomerAnonymizer",
    "DocumentInForce",
    "DocumentKind",
    "Kept",
    "MARKETING_WORDING",
    "consents_of",
    "current_document",
    "document_locales",
    "kept_after_strip",
    "marketing_wording",
    "match_or_create",
    "record_consent",
    "register_customer_anonymizer",
    "strip_customer",
]
