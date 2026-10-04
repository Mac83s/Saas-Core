---
name: develop-commerce-payments
description: Working on what a company sells to its own customers in SaaS Core — orders and their lines, order numbers, the sources that place orders (a booking, later the shop), the buyer and the channel of an order, and from the next slices the customers' payments, the ledger, refunds and the company's bank account. Use when touching modules/shared/commerce, booking's bridge to orders, or anything that places, reprices or cancels an order.
---

# Orders and customers' payments

Read `docs/adr/ADR-073-Zamowienie-Platnosci-Klienta-Koncowego-i-Tryby-Operatora.md`
before changing anything here: §1 and §3 for orders, „Uzupełnienie 2026-10-03:
faza 4 w plastrach” for which slice builds what, and „Rozstrzygnięcia plastra
4e” for why orders look the way they do. The platform's own subscriptions are
another module (`shared.billing`) and another skill.

## What exists

Slice 4e built orders: `Order`, `OrderLine`, a counter of numbers, the registry
of sources, three reads for the panel. Slice 4f-1 added what was paid:
`Payment`, the append-only `LedgerEntry`, a payment the company marks by hand
and takes back when it was a mistake. A transfer with a due date, the
company's bank account, pending bookings, refunds and online payments come
with the next slices of the ADR — do not put a due date, an account or an
operator's field anywhere ahead of them.

## The rules that decide the design

- **Commerce works out no amount.** A line arrives priced from its source — a
  booking's frozen quote, later a basket — with its net, tax and gross. The
  tax is rounded on the line (ADR-072 §7), so a line's totals are never
  `quantity × unit`, and an order's totals are the sum of its lines.
- **A placed line is never changed.** A source that prices its record again
  calls `reprice_order`: the new lines are the next revision, `Order.revision`
  says which are in force, and the database refuses an update or a delete of
  `commerce_orderline` outside a tenant's erasure. Never "fix" a line.
- **The source places its order in its own transaction** — `place_order`
  refuses to run outside one — so there is no booking without its order and no
  order without its booking. It answers None where the company's plan has no
  orders (`commerce.enabled`), and the source goes on as it did before orders.
- **Commerce never imports a source.** A source registers itself from its
  `AppConfig.ready` (`register_order_source(kind, prefix, targets=…)`) and
  calls `commerce.api`. A module that works without commerce — booking does,
  because products leave commerce out — imports it late and only where
  `shared.commerce` is in `ACTIVE_MODULES`; the pattern is
  `apps/backend/src/saas_core/modules/shared/booking/orders.py`.
- **A number is given once.** `{prefix}/{year}/{NNNN}` comes from a counter row
  per company, prefix and year, locked until the order's transaction ends; the
  year is the company's, not the server's.
- **The buyer on an order is a copy of personal data.** `strip_buyer` clears
  it when the customer is anonymised. Any new copy of a customer's data here
  (invoice details, a delivery address) is cleared in the same place and gets
  its row in `docs/architecture/privacy-retention.md`.
- **The audit never names the buyer** — the history is read by whoever manages
  settings. A number, a source, an amount.
- **The ledger decides about money.** What was paid is the sum of an order's
  `charge` and `refund` entries (`ledger.paid_minor`); what is left is the
  lines in force less that sum; `status` is a shortcut for lists derived from
  both in one function, `ledger.status_for`. Never store a paid amount, never
  set a status by hand, never rewrite an entry: a mistake is taken back by the
  opposite entry, and the database refuses anything else.
- **A person marks only what a person can know.** `cash` (at the desk) and
  `transfer`; an online payment is the operator's to confirm.
- **A write on an order names the version it read** (`expected_version`): a
  repeat at the same version is 409 `order_version_conflict` and writes
  nothing, so a payment is never marked twice. Bump `Order.version` with every
  change.

## A new source of orders

1. Register it from the module's `AppConfig.ready`, with its own prefix (two
   sources never number into one sequence) and a `targets` function that names
   what its lines stand for — never with a customer's name.
2. Build `OrderLineInput`s from what the module already priced; give every line
   its `source` and `source_reference` as strings, never a foreign key.
3. Tell the order what happened afterwards: find it with `order_for` (it locks
   the row), then `reprice_order` or `cancel_order`.
4. Test it with the feature on, with the feature off and with the module left
   out of `ACTIVE_MODULES`; the examples are in
   `apps/backend/tests/test_commerce_orders.py`.

## Traps

- **Companies on an earlier plan version have no orders.** The feature is
  published as a new version of every plan; a subscription gets it when it
  moves to that version or by an operator's override. A test company has only
  `booking.enabled` until the test adds `commerce.enabled` to its snapshot.
- **Enum names in the contract are pinned.** A field called `status`, `channel`
  or `kind` collides with other modules' enums and renames them in the
  generated client. The serializers use value-only choices and
  `ENUM_NAME_OVERRIDES` in
  `apps/backend/src/saas_core/config/settings/base.py` names them — as values,
  because a product may leave the module out. After `pnpm api:schema` read the
  diff of `packages/contracts/openapi/v1.yaml` for removed lines.
- **Registering a source again replaces it**, `targets` included: a test that
  re-registers `booking` leaves every later test without the visits' names.
- **`django.utils.timezone` is one object.** Patching `timezone.now` through
  commerce's import patches it for the booking under test too; replace the
  `timezone` name in `commerce.orders` instead.
- **The test database does not prove isolation** — read `change-tenant-data`.
  Prove the three tables on a running stack as the application's role.

## Done means

```
pnpm backend:test
pnpm api:check
pnpm deployment:check:all
```

plus a test of the refusal cases — no permission, a plan without orders,
another company's order — and, for a change of tables, the isolation shown on a
running stack.
