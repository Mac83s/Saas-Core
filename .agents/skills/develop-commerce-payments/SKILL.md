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
and takes back when it was a mistake. Slice 4f-2 added the transfer with a
date: the company's bank account (the settings group `commerce.transfer`), a
payment a source asks for before it confirms (`request_prepayment`), the
source's handler and the deadlines' task („Rozstrzygnięcia plastra 4f-2”).
Slice 4g added draft orders for bookings that wait for the company's answer.
Refunds, a balance's reminders and online payments come with the next slices
of the ADR — do not put an operator's field or a refund anywhere ahead of
them.

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
- **The source asks for a prepayment, commerce sets its date.**
  `request_prepayment` is called by the source right after `place_order`, with
  an amount the source worked out; commerce answers until when the source
  holds its record, or None where nothing can be paid ahead (no bank account)
  — the source then confirms at once. The date is `Payment.due_at`; whatever a
  source shows (`Appointment.hold_expires_at`) is a copy.
- **Which came first is told through the handler.** A source that asks for a
  prepayment registers an `OrderHandler`: `prepaid(order)` when the awaited
  amount was marked, `expired(order)` from the deadlines' task after it
  canceled the order. Both run in the transaction and tenant of the change
  that caused them; never call a source any other way.
- **A booking that waits is booking's state, told by commerce** (ADR-072
  §9): `pending_payment` holds its time with the allocations of a confirmed
  booking. `record_new_booking` decides it from the quote's `prepayment` and
  commerce's answer; `confirm_pending` and `expire_pending` are called by the
  handler, never by a task of booking's own. The confirmation, the reminder,
  the materials, the people's notices and the observers' `CREATED` come at
  confirmation; a pending booking is called off or paid, never moved,
  completed or marked a no-show.
- **What the source has not accepted yet is a draft.** A customer's booking of
  an offer taken „on request” (`pending_request`, booking's own state and
  booking's own expiry task) places its order with `draft=True`: no number, no
  payment (`order_not_placed`), nothing asked for. `accept_order` gives the
  number when the company accepts — only then does the source ask for a
  prepayment — and a request declined, withdrawn or expired cancels the draft,
  so the numbering has no gaps („Rozstrzygnięcia plastra 4g”).
- **A late balance cancels nothing** (owner decision 29a). Only the kinds in
  `PREPAYMENT_KINDS` expire an order; taking a payment back never un-confirms
  what the source confirmed.
- **The deadlines' task reads a route, not a tenant.** `commerce_paymentroute`
  carries ids and a date, never a buyer's data, and a `service` contract of
  the role `commerce_deadlines`; a module's own scheduled work for the
  organization is signed the same way, under a role it registered
  (`register_service_scope`).
- **The account customers pay to is changed by a person with a code.** The
  group `commerce.transfer` asks for a step-up and has no assistant command;
  it is not cleared while an offer asks for a transfer
  (`register_transfer_account_use`) or a transfer is awaited.

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
5. A source that confirms only after a payment: `request_prepayment` after
   `place_order`, a handler in `register_order_source`, and a test of both
   ends — marked in time and expired — as in
   `apps/backend/tests/test_commerce_prepayments.py`.

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
