"use client";

import { useId, useState } from "react";

import { getPublicStayEnds, getPublicStayStarts } from "@saas-core/api-client";
import {
  siteUiTexts,
  stayFormHref,
  type StayBlockV1Data,
  type StayLive,
} from "@saas-core/site-blocks";

import { formatDay, wallClock } from "./calendar-time";
import { StayDatePicker, type StayDateLabels } from "./stay-date-picker";

/**
 * The interactive part of a stay block on a company's own site (ADR-072,
 * slice 5d): the booking widget (`search`) — the days and how many people
 * come — and the calendar of free days. Both lead to the company's booking
 * form with what was chosen; nothing is booked or priced here. The offers
 * are the server's answer for the block (`live`); the free days are read
 * from the form's own API at this host, a month at a time.
 */
export function SiteStayBlock({
  data,
  kind,
  live,
  locale,
}: {
  data: StayBlockV1Data;
  kind: "search" | "calendar";
  live: StayLive;
  /** The page's language; the words come from the site's catalogue. */
  locale: string;
}) {
  const texts = siteUiTexts(locale).stay;
  const id = useId();
  const [offerId, setOfferId] = useState(live.offers[0]?.id ?? "");
  const offer =
    live.offers.find((item) => item.id === offerId) ?? live.offers[0];
  const [chosen, setChosen] = useState("");
  const choice =
    offer?.choices.find((item) => `${item.kind}:${item.id}` === chosen) ??
    offer?.choices[0];
  const unit = offer?.range_unit === "day" ? "day" : "night";
  const [days, setDays] = useState({ start: "", end: "" });
  // Kept as typed, so the field can be emptied on the way to another number.
  const [people, setPeople] = useState("2");
  // The widget opens its calendar when a date is asked for; the calendar
  // block is one.
  const [open, setOpen] = useState(kind === "calendar");
  // The company's today: its calendar, not the browser's.
  const [today] = useState(() => wallClock(new Date(), live.timezone).day);
  if (!offer || !choice) return null;

  const target =
    choice.kind === "group"
      ? { group_id: choice.id }
      : { resource_id: choice.id };
  const labels: StayDateLabels = {
    previousMonth: texts.previousMonth,
    nextMonth: texts.nextMonth,
    pickStart: texts.pick(unit, "start"),
    pickEnd: texts.pick(unit, "end"),
    start: texts.arrival(unit),
    end: texts.departure(unit),
    free: texts.free,
    unavailable: texts.unavailable,
    clear: texts.clear,
    loading: texts.loading,
    loadError: texts.loadError,
    noDays: texts.noDays,
    length: (count) => texts.length(count, unit),
  };
  const count = Math.max(0, Math.floor(Number(people)) || 0);
  const href = stayFormHref(live.form_url, {
    offer: offer.id,
    choice,
    from: days.start,
    // A departure without an arrival says nothing.
    to: days.start ? days.end : "",
    ...(kind === "search" && count ? { people: count } : {}),
  });
  const restart = () => setDays({ start: "", end: "" });
  const shown = (day: string) =>
    day
      ? formatDay(day, locale, {
          weekday: "short",
          day: "numeric",
          month: "long",
        })
      : "—";

  return (
    <div className="site-stay-form">
      {live.offers.length > 1 ||
      offer.choices.length > 1 ||
      kind === "search" ? (
        <div className="site-stay-form__fields">
          {live.offers.length > 1 ? (
            <label className="site-stay-form__field" htmlFor={`${id}-offer`}>
              {texts.offer}
              <select
                id={`${id}-offer`}
                onChange={(event) => {
                  setOfferId(event.target.value);
                  setChosen("");
                  restart();
                }}
                value={offer.id}
              >
                {live.offers.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {offer.choices.length > 1 ? (
            <label className="site-stay-form__field" htmlFor={`${id}-choice`}>
              {texts.choice}
              <select
                id={`${id}-choice`}
                onChange={(event) => {
                  setChosen(event.target.value);
                  restart();
                }}
                value={`${choice.kind}:${choice.id}`}
              >
                {offer.choices.map((item) => (
                  <option
                    key={`${item.kind}:${item.id}`}
                    value={`${item.kind}:${item.id}`}
                  >
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {kind === "search" ? (
            <>
              <div className="site-stay-form__field">
                <div className="site-stay-form__dates">
                  {(["start", "end"] as const).map((edge) => (
                    <button
                      aria-controls={`${id}-calendar`}
                      aria-expanded={open}
                      className="site-stay-form__date"
                      disabled={live.paused}
                      key={edge}
                      onClick={() => setOpen(!open)}
                      type="button"
                    >
                      <small>
                        {edge === "start"
                          ? texts.arrival(unit)
                          : texts.departure(unit)}
                      </small>
                      {shown(days[edge])}
                    </button>
                  ))}
                </div>
              </div>
              <label className="site-stay-form__field" htmlFor={`${id}-people`}>
                {texts.guests}
                <input
                  id={`${id}-people`}
                  inputMode="numeric"
                  max={choice.capacity ?? 99}
                  min={1}
                  onChange={(event) => setPeople(event.target.value)}
                  type="number"
                  value={people}
                />
              </label>
            </>
          ) : null}
        </div>
      ) : null}
      {live.paused ? (
        <p className="site-stay-form__note" role="note">
          {texts.paused}
        </p>
      ) : (
        <div hidden={!open} id={`${id}-calendar`}>
          {open ? (
            <StayDatePicker
              end={days.end}
              labels={labels}
              lastDay={live.last_day}
              loadEnds={(start) =>
                getPublicStayEnds(live.slug, {
                  service_id: offer.id,
                  ...target,
                  start,
                })
              }
              loadStarts={(from, to) =>
                getPublicStayStarts(live.slug, {
                  service_id: offer.id,
                  ...target,
                  from,
                  to,
                })
              }
              locale={locale}
              months={2}
              onChange={(start, end) => setDays({ start, end })}
              searchKey={`${offer.id}:${choice.kind}:${choice.id}`}
              start={days.start}
              today={today}
              unit={unit}
            />
          ) : null}
        </div>
      )}
      <a className="site-section__action" href={href} rel="nofollow">
        {data.action_label || texts.checkDates}
      </a>
    </div>
  );
}
