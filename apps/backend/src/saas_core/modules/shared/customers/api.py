"""Public use-case API of the Customers module (ADR-073 §2).

A company's end customer is one record for bookings, orders and the shop.
Another module reaches it through this file: `CUSTOMER_MODEL` for its own
foreign key, `match_or_create` on a first booking or order, and
`register_customer_anonymizer` for what it stores about a customer beside the
customer's row.

The company's documents for its customers (§9) are read and agreed to through
two calls, both made inside the tenant the caller already holds — a public
form's service context is enough: `current_document(kind, locale)` gives the
text in force in exactly that language (or None — never another language),
and `record_consent(...)` appends who saw which text row to the journal;
`consents_of(source, references)` reads the lines written for a source's
records back, for the screen that shows the record.
"""

from .documents import DocumentInForce, consents_of, current_document, record_consent
from .models import ConsentKind, Customer, DocumentKind
from .services import (
    CustomerAnonymizer,
    match_or_create,
    register_customer_anonymizer,
    strip_customer,
)

CUSTOMER_MODEL = "customers.Customer"

__all__ = [
    "CUSTOMER_MODEL",
    "ConsentKind",
    "Customer",
    "CustomerAnonymizer",
    "DocumentInForce",
    "DocumentKind",
    "consents_of",
    "current_document",
    "match_or_create",
    "record_consent",
    "register_customer_anonymizer",
    "strip_customer",
]
