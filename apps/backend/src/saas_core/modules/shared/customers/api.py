"""Public use-case API of the Customers module (ADR-073 §2).

A company's end customer is one record for bookings, orders and the shop.
Another module reaches it through this file: `CUSTOMER_MODEL` for its own
foreign key, `match_or_create` on a first booking or order, and
`register_customer_anonymizer` for what it stores about a customer beside the
customer's row.
"""

from .models import Customer
from .services import (
    CustomerAnonymizer,
    match_or_create,
    register_customer_anonymizer,
    strip_customer,
)

CUSTOMER_MODEL = "customers.Customer"

__all__ = [
    "CUSTOMER_MODEL",
    "Customer",
    "CustomerAnonymizer",
    "match_or_create",
    "register_customer_anonymizer",
    "strip_customer",
]
