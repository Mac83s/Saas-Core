---
name: develop-booking
description: Working on scheduling in SaaS Core — services, staff, resources, availability rules, time off, slot search, appointments, rescheduling and cancellation, the end customer, self-service links and public booking. Use when touching modules/shared/booking, availability or anything that computes or reserves time.
---

# Booking: time, conflicts and the end customer

Read `docs/adr/ADR-030-Booking-Czas-Blokady-i-Self-Service.md` before changing
anything here. Two thirds of the decisions in this module exist because time and
concurrency are both harder than they look.

## Time

- **Instants are UTC; weekly rules are local.** An appointment and a time-off
  window are stored as UTC. An availability rule is a weekday plus a local time,
  interpreted in `Organization.timezone` through IANA `zoneinfo` at the moment
  slots are computed. Storing rules in UTC would shift a business's opening hour
  twice a year.
- **DST is not an edge case, it is a Sunday.** A local time that does not exist
  during the spring transition is skipped; an ambiguous local time in autumn
  produces **two** instants with different offsets. Results are sorted by UTC and
  deduplicated — a slot list that shows the same wall-clock hour twice in
  October is correct.
- **A slot is the service duration plus its buffers**, not the duration. The
  public horizon is at most 62 days, because an open horizon is a scraping
  surface and a slow query at once. Search is days first (one free start per
  day), then the times of one day; a booking checks its one start with
  `validate_start` (ADR-058 §5). Never cap results in the middle of a day, and
  never validate a start by looking it up in a capped list — that is how a free
  afternoon of the last-added person became "unavailable".
- **The server picks the person** when the caller names nobody: least minutes
  booked that local day, then that week, then id, trying the next one in a
  savepoint when the exclusion constraint takes the first (ADR-058 §4). A
  frontend that sends the first slot's `staff_id` hands every visit to the
  oldest calendar entry.
- **An appointment keeps a snapshot** of its time and service name. Editing the
  catalogue or the schedule later must not rewrite what a customer booked.

## Conflicts

Staff and resource occupancy are materialized as separate allocation rows, and
the last word belongs to PostgreSQL:

```
EXCLUDE USING gist ON (organization, staff/resource, tstzrange) WHERE active
```

That constraint is the race resolution. Python checks are for good error
messages, never for correctness — `select_for_update` cannot help when the thing
you want to lock is a row that does not exist yet.

Create, reschedule and cancel each carry an idempotency key and a request hash.
Reschedule deactivates the old allocations and creates the new ones **in one
transaction**; there is no window in which a customer holds neither slot or both.

A conflict must surface as a slot conflict the caller can act on. If a database
error reaches the API as a 500 or a deadlock, that is a defect in this module,
not in PostgreSQL.

## The end customer

- `Customer` is a **tenant entity independent of `User`**. Guest booking is the
  default and complete; there is no fictional membership for a customer, and
  there will not be one.
- Anonymisation clears contact data without deleting business history. Retention
  is 24 months from the last appointment by default, configurable per deployment.
- **Self-service is a token, not an account.** At least 256 bits of randomness;
  the database stores a digest in a global, PII-free routing index; the token is
  bound to **one** appointment, expires, and is invalidated on cancellation.
- **Public routing starts from a non-personal `public_slug`**, then activates an
  explicit `service` tenant context with the minimum scope
  (`booking.public.read`, `booking.public.manage`). It is not a membership and
  not a global fallback — a public request never reaches an arbitrary tenant.
- Confirmations and reminders go through the durable queue, never sent inline in
  the request. Content stays generic: organization, time, safe link. No medical
  detail, ever, in an email or a log line.

## Traps

- **The routing tables have no tenant policy on purpose.**
  `booking_publicbookingroute`, `booking_selfserviceroute` and
  `booking_reminderroute` are lookup tables that say *which* tenant to set
  before anything else is read. They carry identifiers, never customer data — if
  you are tempted to add a name to one, that is the signal you are on the wrong
  table.
- **Everything else in Booking is under forced RLS.** Read `change-tenant-data`
  before adding a model or a task here.
- **A reminder route is the organization's, not the booker's.** It is signed
  as a `service` contract (`booking_reminder`) and re-armed by `_arm_reminder`
  on every move (ADR-058 §7). Signed with the caller's membership it dies when
  that person leaves — and an unopenable route used to head the queue forever.
- **Payments are out of scope** until ADR-037 comes back with P5. Do not add a
  deposit field "for later".

## Done means

```
pnpm backend:test
pnpm api:check
```

plus a test for the concurrent case — two bookings racing for one slot, and a
reschedule that must not leave an allocation behind. The authorization matrix in
`docs/architecture/testing-strategy.md` applies to every public endpoint,
including the one reached by a self-service token.
