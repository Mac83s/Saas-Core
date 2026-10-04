"""The plan feature and the permissions of commerce, named once."""

#: The company's plan has orders of its customers.
COMMERCE_ENABLED = "commerce.enabled"
ORDERS_READ = "commerce.orders.read"
#: Marking what a customer paid, and the account customers pay to.
PAYMENTS_MANAGE = "commerce.payments.manage"
#: The role the deadlines' task acts under: the organization's own job. The
#: permission is a scope marker nobody's role carries.
DEADLINES_ROLE = "commerce_deadlines"
DEADLINES_PERMISSIONS = frozenset({"commerce.deadlines.run"})
