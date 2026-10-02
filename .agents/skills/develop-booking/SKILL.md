---
name: develop-booking
description: Working on scheduling in SaaS Core — services, staff, resources, availability rules, time off, slot search, appointments, rescheduling and cancellation, the end customer, self-service links and public booking. Use when touching modules/shared/booking, availability or anything that computes or reserves time.
---

# Booking: time, conflicts and the end customer

Read `docs/adr/ADR-030-Booking-Czas-Blokady-i-Self-Service.md` before changing
anything here, and
`docs/adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md`
before touching time models, units, rules, prices, pending bookings or presets.
Two thirds of the decisions in this module exist because time and concurrency
are both harder than they look.

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
- **A `slot` start is the service duration plus its buffers**, not the
  duration. One `slot` query spans at most `BOOKING_SLOT_HORIZON_DAYS` (≤ 62)
  days, because an open window is a scraping surface and a slow query at once;
  a `range` calendar counts days with its own bound and the offer's booking
  window (ADR-072 §5). Search is days first (one free start per
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
- **The people on a visit change only through `crew.set_crew`** (ADR-058,
  phase 3): booking, the office's assignment, a move, an absence, a person
  leaving, a product's join or leave. It keeps the invariant — the lead has an
  active allocation or the visit is a vacancy — bumps `crew_version` and tells
  the people. A product uses `booking.api` (`join_visit_crew`,
  `leave_visit_crew`, `crew_people`, `crew_member_filter`); writing an
  allocation directly leaves a lead nobody blocked and a queue that lies. A
  booking that takes no person (`staff_required = 0`: a unit, a seat in an
  event — ADR-072 §2) has no lead and an empty `Appointment.staff`.
- **Where a visit takes place (ADR-066).** The company's `Location` is where it
  is booked; a field visit happens elsewhere. The visit's own `place_town` and
  `place_address` say it first (set in the form or `PUT …/place/`); where they
  are empty, a product's `booking.api.register_appointment_place(name,
  provider)` may — ids in, town per id out, one call per list. The panel shows
  the result as `place`. A product's `register_place_search` may offer the
  company's places in the form as „Zapisane miejsce” (HoofCare offers its farms
  in its own section instead, ADR-067). The street can be a customer's home:
  never in the audit, cleared on anonymization, and in a visit's payload only
  for whoever sees the customer's phone.
- **A product's kind of visit is booked by the product (ADR-067).** The slot
  `src/product/calendar.tsx` puts its section in „Nowa wizyta” for its
  `appointment_kind`s; the section takes over „Zapisz” and books atomically
  through the product's API. Core has no `details` field on its own POST.
  Products mark visits with `register_appointment_flags`. The customer's phone
  and e-mail in a visit's payload are for `booking.appointment.manage` and the
  people on the visit only (`visible_contacts`); everybody else gets null.

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
- **Prices, payment and cancellation policies and pending states follow
  ADR-072 §6–§9; money lives in the order (ADR-073).** Never add a price or
  deposit field to `Service` or `Appointment` beyond the frozen quote and
  policy snapshot.
- **A person is a `StaffMember`, with an account or without one** (ADR-058 §1,
  `booking/staff.py`). The account joins the entry in one place:
  `staff.link_on_join`, registered through `organizations.joining` because
  core may not import booking. A second linking path next to it — a signal,
  a sweep — would link one person twice or not at all.

## Operable by the AI assistant

Setup (services, locations, resources, staff, teams, schedules) is what the
in-product assistant will configure first, and today it has neither idempotency
keys nor resource versions. A new or changed setup endpoint adds both and meets
`change-api-and-events` § "Operable by the AI assistant".

## Done means

```
pnpm backend:test
pnpm api:check
```

plus a test for the concurrent case — two bookings racing for one slot, and a
reschedule that must not leave an allocation behind. The authorization matrix in
`docs/architecture/testing-strategy.md` applies to every public endpoint,
including the one reached by a self-service token.
