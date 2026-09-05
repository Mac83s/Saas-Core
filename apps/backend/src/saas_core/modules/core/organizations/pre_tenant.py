"""The door from ADR-041, named so it can be counted.

A handful of reads have to happen before anybody knows which tenant is asking:
logging in looks up a membership to build the context, the switcher lists the
companies an account belongs to, an invitation is found by its token by
somebody who is not a member yet, the Stripe processor identifies a customer,
and the background sweeps walk every organization on purpose.

Those reads use this connection. It is a different database role on the same
database, and it sees nothing except through policies that name it explicitly —
it holds no BYPASSRLS, so opening a table to it is a migration somebody writes
and somebody reviews.

The point is not that bypassing is safe. It is that the list of places doing it
can be printed with one command, and `tests/test_pre_tenant_door.py` fails when
that list grows without the list being updated.
"""

from __future__ import annotations

from django.conf import settings

#: Alias of the connection above. Import the constant rather than the string:
#: the test that guards the door looks for this name.
PRE_TENANT_DB: str = settings.PRE_TENANT_DATABASE_ALIAS
