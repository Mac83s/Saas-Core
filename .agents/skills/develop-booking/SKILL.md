---
name: develop-booking
description: Working on scheduling in SaaS Core — services, staff, resources, availability rules, time off, slot search, appointments, rescheduling and cancellation, the end customer, self-service links and public booking; units and unit groups, periods (range), booking and price rules, quotes, pending bookings and presets. Use when touching modules/shared/booking, availability or anything that computes or reserves time.
---

# Booking: time, conflicts and the end customer

Read `docs/adr/ADR-030-Booking-Czas-Blokady-i-Self-Service.md` before changing
anything here, and
`docs/adr/ADR-072-Rezerwacje-Uniwersalne-Modele-Czasu-Jednostki-Reguly-Wycena-Presety.md`
before touching time models, units, rules, prices, pending bookings or presets.

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
  never validate a start by looking it up in a capped list.
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
- **"The visit has passed" is one rule (UX-031), in `passing.py`**: confirmed
  and `ends_at <= now`, derived, never stored. The payload says it as `passed`;
  the panel uses `hasPassed`/`shownStatus` from `appointment-dialogs.tsx`, and
  counting uses `took_place_q`. Do not compare `ends_at` with now anywhere
  else. A passed visit is not ahead („Najbliższe”), and a vacancy on it is
  nobody's work (no Wakat, no queue). It took place by default (3A), unless
  its kind is in the module's
  `appointmentKindsCompletedExplicitly` (`closes_explicitly`; `""` names the
  plain service). The customer who did not come is `mark_no_show` — from the
  visit's start, no undo; it counts as `no_shows`, never as done.
- **What the calendar shows but does not own** (UX-078) comes from a source in
  `apps/frontend/src/lib/calendar-sources.ts`, gated like a menu entry — today
  the companies' visits on a farm's calendar, from `shared.farms`. They are
  read-only cards, never `BookingAppointment`s: keep them out of the
  appointments state, the day board and any count of the team.
- **Whose visits a person sees is one rule (UX-023), in `visibility.py`.**
  Everyone's by default; a product that declares
  `appointmentsOfOthersPermission` (MedPlano: a doctor does not see another
  doctor's patients) limits whoever lacks it and does not plan visits to the
  visits they are on (`sees_others`, `own_visits_q`). Every read of visits
  goes through it — never a second `staff__membership_id` filter of your own.

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

- `Customer` is a **tenant entity independent of `User`**, a record of
  `shared.customers` (ADR-073 §2) reached through `customers.api`. Guest booking
  is the default and complete; a customer never gets a fictional membership.
  Customer data copied onto a visit is cleared in `strip_customer_visits`.
- Anonymisation clears contact data without deleting business history. It is
  manual (`anonymize_customer`) today; automatic deletion after inactivity is off
  by default and a company may turn it on at 12, 24 or 36 months from the last
  appointment (ADR-078, addendum 37a, which changes ADR-036).
- **Self-service is a token, not an account.** At least 256 bits of randomness;
  the database stores a digest in a global, PII-free routing index; the token is
  bound to **one** appointment, expires, and is invalidated on cancellation.
- **Public routing starts from a non-personal `public_slug`**, then activates an
  explicit `service` tenant context with the minimum scope
  (`booking.public.read`, `booking.public.manage`) — never a membership or
  global fallback. Stays too (`public_stay_views.py`): only what is online,
  and a write needs the shown `quote_digest`.
- **A guest gets a unit's content only when it is `public`**
  (`unit_content.py`, ADR-072 5c): pictures, amenities, town — never
  coordinates. The company's site shows the same (`site_blocks.py`, 5d).
- **Who books for themselves accepts the company's documents** (ADR-073 §9,
  `consents.py`): the form reads those in force in the booking's language
  (`shown`) and sends their `text_id`s; `record` checks and journals them,
  else 409 `documents_changed`. Terms with no text in that language close
  online booking in it (409 `booking_language_unavailable`); a ticked
  `consents.marketing` is a journal line. The team's bookings ask nothing.
- Confirmations and reminders go through the durable queue, never inline in
  the request. Content stays generic: organization, time, safe link. No
  medical detail, ever, in an email or a log line.

## Traps

- **The routing tables have no tenant policy on purpose.**
  `booking_publicbookingroute`, `booking_selfserviceroute` and
  `booking_reminderroute` say *which* tenant to set before anything else is
  read. They carry identifiers, never customer data — a name does not belong
  in one.
- **Everything else in Booking is under forced RLS.** Read `change-tenant-data`
  before adding a model or a task here.
- **A reminder route is the organization's, not the booker's.** It is signed
  as a `service` contract (`booking_reminder`) and re-armed by `_arm_reminder`
  on every move (ADR-058 §7). Signed with the caller's membership it dies when
  that person leaves.
- **Prices, payment and cancellation policies and pending states follow
  ADR-072 §6–§9; money lives in the order (ADR-073).** Never add an amount to
  `Service` or `Appointment` beyond the frozen quote: a price is a `PriceRule`,
  a charge or a deposit an `Extra`. What an offer carries is policy — how the
  customer pays (`payment_policy`), the prepayment's terms (see
  develop-commerce-payments) — declared in `offer_settings.py` and frozen into
  each booking's quote. Refund thresholds cover only the deposit unless the
  offer's switch says otherwise (`appliesTo`, decision 28a) — a setting of the
  API, not a column only the panel knows; an unpaid balance never cancels a
  booking on its own (29a).
- **A person is a `StaffMember`, with an account or without one** (ADR-058 §1,
  `booking/staff.py`). The account joins the entry in one place:
  `staff.link_on_join`, registered through `organizations.joining` because
  core may not import booking. A second path — a signal, a sweep — would link
  one person twice or not at all.

## Operable by the AI assistant

Every setup write goes through `setup.setup_write` (ADR-072 §11):

- **a key with a receipt** — `BookingSetupMutation` (not `BookingMutation`,
  which points at a visit); the same key answers the first result again, a
  key reused on another request is 409 `booking_idempotency_conflict`. The
  receipt is written only after the write succeeded;
- **a version** — `Service.version`, `Location.version`, `Resource.version`,
  `StaffMember.hours_version` (the week, not the person: a team change must
  not stale an open week). A change names it (`expected_version`); a stale one
  is 409 `booking_version_conflict`. Bump it only when something changed;
- **a preview** — `preview=True` runs the same write in a savepoint that is
  rolled back, so it refuses exactly what the write would and stores nothing
  (no receipt, no history, no queued work). The API has `…/preview/` next to
  each write, `x-dry-run`.

What an offer can be set to lives in one constant, `offer_settings.py`
(`OFFER_SETTINGS`): bounds, variants, today's defaults, labels. The input
serializer takes its bounds from it and `GET /booking/setup/options/` serves it
in the settings registry's shape (ADR-078), so the registry (R1) replaces the
constant without changing the API. A new offer setting goes there first, never
as a number in a serializer or a component. A new setup write uses
`setup_write`, `check_version` and the floor of `change-api-and-events`.

Presets are data, read by `presets.py` from the image's copy of
`packages/contracts/booking-presets` (`BOOKING_PRESET_CONTRACTS_PATH`, system
check `booking.E010`); `GET /booking/presets/` is the only list a caller
chooses from. `presets.apply_preset` is a setup write that copies a `ready`
preset into a switched-off offer with its origin (`preset_id`,
`preset_version`, `origin_ref`) and picks nobody, no place, no unit and no
price for the company. Ready means the engine runs it (the contract test's
`ENGINE` list), not that customers book it: `online_booking` `soon` (decision
67a) makes an offer hidden from the public form, which the team books.
A service made switched off is a `draft` until somebody switches it on, and
**only a draft without bookings is ever deleted** (`setup.discard_draft`, the
undo of commands that make drafts). Every other service is switched off, never
removed.

The price list is `prices.py` (ADR-072 §6): a `PriceRule` prices an offer, a
group or a unit — the base price without dates, a season's with them, a
weekend's or a peak's with weekdays and hours — and `price_for` picks the one
that applies: one for some days only (a season, weekdays, hours) over a base
price, whoever it is for (decision 75b); then the unit's over its group's over
the offer's, a season's over one without dates, the narrower over the wider,
the later start. Amounts are whole minor units, gross or net by the
company's `pricing.entry.amounts`; the tax is a code (`VatCode`), because
exempt is not 0%. A rule's currency is always
`Organization.currency`, and a company with prices cannot change its currency
(`register_currency_use`, `currency_in_use`). An `Extra` belongs to one offer:
mandatory, or picked by the customer; of kind `security_deposit` it is the
amount held and given back, which a quote names beside its totals and never
in them. A `ParticipantCategory` and an `Extra` are never deleted, only
switched off: frozen quotes name them.

A booking's price is worked out in one place, `quote.py` (ADR-072 §7):
`quote_visit` and `quote_stay` write nothing, and every booking path — the
panel, the public form, a product through `booking.api` — works the price out
again inside its transaction and freezes it in `Appointment.quote`. Never
compute an amount anywhere else, and never read the price list to show a
price: ask for a quote. The tax is rounded on each line, halves up; a caller
that showed a price sends its `digest` back (`quote_digest`) and gets 409
`quote_changed` with the new quote when it moved. A booking moved is priced
again for the same people; one from before quotes has none and gets none.
A customer reads a quote through `quote.customer_quote`: gross, in their
language, without the company's net, tax and ids — the public form and the
customer's own link never serialize the full snapshot.

The price list's panel is `apps/frontend/src/modules/shared/booking/prices/`:
each offer's „Cennik” and the stays' prices under „Sezony”. It shows amounts
as entered and asks the server for every price a booking would have —
`PanelQuote` draws a quote, nothing adds one up. The preview „Jaka cena
obowiązuje dnia…” asks `POST /booking/quote/` with `price_only`, which answers
for a time that cannot be booked (a taken unit, a season's rule, an offer
switched off); a booking never sends it. Which price won is the line's
`price_rule_id`. „Za osobę za noc” is a price per time unit of 0 with nobody
included: `quote` leaves out the line of 0 and names the people by the offer
(`_per_person_only`).

## Done means

```
pnpm backend:test
pnpm api:check
```

plus a test for the concurrent case — two bookings racing for one slot, a
reschedule that leaves no allocation behind. The authorization matrix in
`docs/architecture/testing-strategy.md` applies to every public endpoint,
self-service links included.
