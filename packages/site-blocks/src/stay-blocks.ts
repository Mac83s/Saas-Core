import { createElement as h, type ReactNode } from "react";

import { renderImage } from "./ai-badge";
import { plainBlockText } from "./block-text";
import { siteUiTexts, type StayTexts } from "./site-ui-texts";
import type {
  BlockComponentProps,
  BlockImageRenderer,
  PriceConversion,
  StayBlockV1Data,
  StayLive,
  StayLiveChoice,
  StayLiveOffer,
  StayMapLive,
  StayMapV1Data,
  StayPlace,
  StayUnitV1Data,
} from "./types";

/** What a link to the company's booking form may say ahead of the guest:
 *  the offer, what is booked of it, the days and how many people come. */
export type StayPick = {
  offer?: string;
  choice?: Pick<StayLiveChoice, "kind" | "id">;
  from?: string;
  to?: string;
  people?: number;
};

/** The form's address with what the guest already chose. The form reads the
 *  same names (`offer`, `group` or `unit`, `from`, `to`, `people`) and asks
 *  the server about every one of them again. */
export function stayFormHref(formUrl: string, pick: StayPick = {}): string {
  const query = new URLSearchParams();
  if (pick.offer) query.set("offer", pick.offer);
  if (pick.choice) query.set(pick.choice.kind, pick.choice.id);
  if (pick.from) query.set("from", pick.from);
  if (pick.to) query.set("to", pick.to);
  if (pick.people) query.set("people", String(pick.people));
  const text = query.toString();
  return text ? `${formUrl}?${text}` : formUrl;
}

/** „300 zł”, „299,50 zł”: whole amounts without the grosze. */
export function stayAmount(
  price: NonNullable<StayLiveChoice["from_price"]>,
  locale: string,
): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: price.currency,
    minimumFractionDigits: price.gross_minor % 100 === 0 ? 0 : 2,
  }).format(price.gross_minor / 100);
}

/** „≈ 69 €”: an amount of the company's in the reader's own currency, at
 *  the bank's rate the server gave (ADR-072, slice 5i). Whole units from ten
 *  up — it is a rough figure, and says so by its sign. Empty without a rate.
 *  Information beside a price: the price itself is never replaced. */
export function approxAmount(
  minor: number,
  conversion: PriceConversion | null | undefined,
  locale: string,
): string {
  const rate = Number(conversion?.rate);
  if (!conversion || !(rate > 0)) return "";
  const value = (minor * rate) / 100;
  const digits = value >= 10 ? 0 : 2;
  return `≈ ${new Intl.NumberFormat(locale, {
    style: "currency",
    currency: conversion.currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)}`;
}

/** The day of the bank's table as the page's language writes a date. */
export function conversionDay(
  conversion: PriceConversion,
  locale: string,
): string {
  const day = new Date(`${conversion.date}T00:00:00Z`);
  return Number.isNaN(day.getTime())
    ? conversion.date
    : new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeZone: "UTC",
      }).format(day);
}

/** „od 300 zł / noc ≈ 69 €”: the company's price, and beside it the rough
 *  figure in the reader's currency where the server gave a rate. */
function fromPrice(
  price: NonNullable<StayLiveChoice["from_price"]>,
  live: StayLive,
  texts: StayTexts,
  locale: string,
): ReactNode {
  const approx = approxAmount(price.gross_minor, live.conversion, locale);
  return h(
    "p",
    { className: "site-stay-unit__price" },
    texts.fromPrice(stayAmount(price, locale), price.per),
    approx
      ? h("span", { className: "site-stay-unit__approx" }, ` ${approx}`)
      : null,
  );
}

/** What the rough figures are, said once under what shows them: whose rate,
 *  of which day, and that the booking and the payment are in the company's
 *  currency. Nothing where no figure was shown. */
function approxNote(
  live: StayLive,
  prices: readonly (StayLiveChoice["from_price"] | undefined)[],
  texts: StayTexts,
  locale: string,
): ReactNode {
  const currency = prices.find((price) => price)?.currency;
  if (!live.conversion || !currency || !(Number(live.conversion.rate) > 0))
    return null;
  return h(
    "p",
    { className: "site-stay__approx-note" },
    texts.approxNote(
      conversionDay(live.conversion, locale),
      live.conversion.bank,
      currency,
    ),
  );
}

/** The company's own words in another language than the page's say so
 *  (slice 5i): a screen reader then reads them in their language, and a
 *  translating browser knows what to leave alone or translate. */
function spoken(lang: string | undefined, locale: string): { lang?: string } {
  return lang && lang !== locale ? { lang } : {};
}

/** One picture of a unit at the site's own host: our two copies, never the
 *  original — as the company's form serves it. Handed to the page's renderer
 *  like any block's picture: its size, the AI marking, which load first. */
function unitPhoto(
  assetId: string,
  alt: string,
  sizes: string,
  imageRenderer: BlockImageRenderer | undefined,
): ReactNode {
  const base = `/media/${assetId}`;
  return renderImage(
    { asset_id: assetId, alt },
    h("img", {
      src: `${base}/preview`,
      srcSet: `${base}/thumbnail 320w, ${base}/preview 1280w`,
      sizes,
      alt,
      loading: "lazy",
      decoding: "async",
    }),
    imageRenderer,
  );
}

/** How many amenities a card names before „+N”. */
const SHOWN_AMENITIES = 6;

function unitCard(
  live: StayLive,
  offer: StayLiveOffer,
  choice: StayLiveChoice,
  texts: StayTexts,
  locale: string,
  heading: "h3" | "h4",
  actionLabel: string,
  sizes: string,
  imageRenderer: BlockImageRenderer | undefined,
): ReactNode {
  const href = stayFormHref(live.form_url, { offer: offer.id, choice });
  const cover = choice.photos?.[0];
  const amenities = choice.amenities ?? [];
  const facts = [
    choice.town?.name,
    choice.capacity ? texts.capacity(choice.capacity) : undefined,
  ].filter(Boolean);
  return h(
    "li",
    {
      key: `${offer.id}:${choice.kind}:${choice.id}`,
      className: "site-stay-unit",
    },
    cover
      ? h(
          "div",
          { className: "site-stay-unit__cover" },
          unitPhoto(cover, choice.name, sizes, imageRenderer),
        )
      : null,
    h(
      "div",
      { className: "site-stay-unit__body" },
      h(
        heading,
        { className: "site-stay-unit__name", ...spoken(choice.lang, locale) },
        // The unit's own page, where the site has one: its pictures, all it
        // has and its calendar.
        choice.page_path
          ? h("a", { href: choice.page_path }, choice.name)
          : choice.name,
      ),
      facts.length
        ? h("p", { className: "site-stay-unit__facts" }, facts.join(" · "))
        : null,
      choice.description
        ? h(
            "p",
            {
              className: "site-stay-unit__text",
              ...spoken(choice.description_lang, locale),
            },
            choice.description,
          )
        : null,
      amenities.length
        ? h(
            "ul",
            { className: "site-stay-unit__amenities" },
            ...amenities
              .slice(0, SHOWN_AMENITIES)
              .map((item) => h("li", { key: item.key }, item.label)),
            amenities.length > SHOWN_AMENITIES
              ? h(
                  "li",
                  { key: "more" },
                  `+${amenities.length - SHOWN_AMENITIES}`,
                )
              : null,
          )
        : null,
      h(
        "div",
        { className: "site-stay-unit__foot" },
        choice.from_price
          ? fromPrice(choice.from_price, live, texts, locale)
          : null,
        h(
          "a",
          {
            className: "site-section__action",
            href,
            rel: "nofollow",
            // The same words on every card: the name says which one.
            "aria-label": `${actionLabel}: ${choice.name}`,
          },
          actionLabel,
        ),
      ),
    ),
  );
}

/** Where a unit's own page leads on (`others` of the server's answer): a
 *  few of the company's other units, small — the cover, the name, the town
 *  and how many it takes, „od X zł / noc” — each card one link to that
 *  unit's page. Nothing to go on to — nothing drawn. */
function otherUnits(
  others: readonly StayLiveChoice[] | undefined,
  texts: StayTexts,
  locale: string,
  imageRenderer: BlockImageRenderer | undefined,
): ReactNode {
  const shown = (others ?? []).filter((other) => other.page_path);
  if (!shown.length) return null;
  return h(
    "div",
    { className: "site-stay-others" },
    h("h2", null, texts.others),
    h(
      "ul",
      { className: "site-stay-others__list" },
      ...shown.map((other) => {
        const cover = other.photos?.[0];
        const facts = [
          other.town?.name,
          other.capacity ? texts.capacity(other.capacity) : undefined,
        ].filter(Boolean);
        return h(
          "li",
          { key: `${other.kind}:${other.id}`, className: "site-stay-other" },
          h(
            "div",
            { className: "site-stay-other__cover" },
            cover ? unitPhoto(cover, other.name, "8rem", imageRenderer) : null,
          ),
          h(
            "div",
            { className: "site-stay-other__body" },
            h(
              "h3",
              {
                className: "site-stay-unit__name",
                ...spoken(other.lang, locale),
              },
              h("a", { href: other.page_path }, other.name),
            ),
            facts.length
              ? h(
                  "p",
                  { className: "site-stay-unit__facts" },
                  facts.join(" · "),
                )
              : null,
            other.from_price
              ? h(
                  "p",
                  { className: "site-stay-unit__price" },
                  texts.fromPrice(
                    stayAmount(other.from_price, locale),
                    other.from_price.per,
                  ),
                )
              : null,
          ),
        );
      }),
    ),
  );
}

function intro(
  data: StayBlockV1Data,
  editor: BlockComponentProps["editor"],
): ReactNode {
  const text = editor?.text ?? plainBlockText;
  return h(
    "div",
    { className: "site-section__intro" },
    h(
      "h2",
      editor ? { role: "presentation" } : null,
      text(["title"], data.title),
    ),
    data.text
      ? h("p", { className: "site-section__lead" }, text(["text"], data.text))
      : null,
  );
}

function previewNote(note: string): ReactNode {
  return h("p", { className: "site-stay__preview-note" }, note);
}

/**
 * The company's units booked from–to (ADR-072, slice 5d): a cover, the name,
 * the town and how many people it takes, what it has, „od X zł / noc” and the
 * way to the form with the unit already chosen. Plain markup from the
 * server's answer — nothing here asks for anything. The editor shows where
 * the list will be: the units live in the booking settings, not on the page.
 */
export function StayUnitsBlock({
  data,
  editor,
  imageRenderer,
  live,
  options,
}: BlockComponentProps) {
  const block = data as StayBlockV1Data;
  const locale = options?.locale ?? "pl";
  const texts = siteUiTexts(locale).stay;
  const layout = block.layout ?? "cards";
  const shown = live?.data as StayLive | undefined;
  const actionLabel = block.action_label || texts.book;
  const sizes =
    layout === "rows"
      ? "(min-width: 48rem) 40vw, 100vw"
      : "(min-width: 64rem) 33vw, (min-width: 48rem) 50vw, 100vw";
  const list = (offer: StayLiveOffer, heading: "h3" | "h4") =>
    h(
      "ul",
      { className: "site-stay-units__list" },
      ...offer.choices.map((choice) =>
        unitCard(
          shown!,
          offer,
          choice,
          texts,
          locale,
          heading,
          actionLabel,
          sizes,
          imageRenderer,
        ),
      ),
    );
  return h(
    "section",
    {
      className: `site-block site-block--stay-units site-stay-units--${layout}`,
      "data-block-type": "core.stay_units",
      "data-section-layout": layout,
    },
    intro(block, editor),
    shown
      ? shown.offers.length === 1
        ? list(shown.offers[0]!, "h3")
        : shown.offers.map((offer) =>
            h(
              "div",
              { key: offer.id, className: "site-stay-units__offer" },
              h("h3", null, offer.name),
              list(offer, "h4"),
            ),
          )
      : h(
          "div",
          { className: "site-stay__preview" },
          h(
            "ul",
            { className: "site-stay-units__list", "aria-hidden": true },
            ...[0, 1, 2].map((index) =>
              h(
                "li",
                {
                  key: index,
                  className: "site-stay-unit site-stay-unit--sample",
                },
                h("div", { className: "site-stay-unit__cover" }),
                h(
                  "div",
                  { className: "site-stay-unit__body" },
                  h("span", { className: "site-stay-unit__line" }),
                  h("span", { className: "site-stay-unit__line" }),
                  h(
                    "span",
                    { className: "site-section__action" },
                    // One place to edit the words; the other sample cards
                    // repeat them.
                    editor && block.action_label && index === 0
                      ? editor.text(["action_label"], block.action_label)
                      : actionLabel,
                  ),
                ),
              ),
            ),
          ),
          previewNote(texts.preview.units),
        ),
    // Under the cards: what the rough figures beside the prices are.
    shown
      ? approxNote(
          shown,
          shown.offers.flatMap((offer) =>
            offer.choices.map((choice) => choice.from_price),
          ),
          texts,
          locale,
        )
      : null,
  );
}

/** The part of a widget or a calendar that is the same: its heading, and on
 *  a published page the application's own component, which asks the form's
 *  API for free days. Without one — a renderer that brought none — the way
 *  to the form is still there. */
function interactive(
  kind: "search" | "calendar",
  { data, editor, live, options }: BlockComponentProps,
): ReactNode {
  const block = data as StayBlockV1Data;
  const texts = siteUiTexts(options?.locale ?? "pl").stay;
  const shown = live?.data as StayLive | undefined;
  const label = block.action_label || texts.checkDates;
  return h(
    "section",
    {
      className: `site-block site-block--stay-${kind}`,
      "data-block-type": `core.stay_${kind}`,
    },
    intro(block, editor),
    h(
      "div",
      { className: "site-stay__body" },
      shown
        ? (live?.render?.(`core.stay_${kind}`, data, live.data) ??
            h(
              "a",
              {
                className: "site-section__action",
                href: stayFormHref(shown.form_url, { offer: block.offer }),
                rel: "nofollow",
              },
              label,
            ))
        : h(
            "div",
            { className: "site-stay__preview" },
            h(
              "div",
              {
                className: `site-stay__sample site-stay__sample--${kind}`,
                "aria-hidden": true,
              },
              ...(kind === "search"
                ? [
                    texts.arrival("night"),
                    texts.departure("night"),
                    texts.guests,
                  ]
                : []
              ).map((field) =>
                h(
                  "span",
                  { key: field, className: "site-stay__sample-field" },
                  field,
                ),
              ),
              kind === "calendar"
                ? Array.from({ length: 35 }, (_, index) =>
                    h("span", {
                      key: index,
                      className: "site-stay__sample-day",
                    }),
                  )
                : null,
            ),
            h(
              "span",
              { className: "site-section__action" },
              editor && block.action_label
                ? editor.text(["action_label"], block.action_label)
                : label,
            ),
            previewNote(texts.preview[kind]),
          ),
    ),
  );
}

/** Dates and how many people come, then the form with them filled in. */
export function StaySearchBlock(props: BlockComponentProps) {
  return interactive("search", props);
}

/** The months with the days a stay can begin on; a day picked leads to the
 *  form. */
export function StayCalendarBlock(props: BlockComponentProps) {
  return interactive("calendar", props);
}

/**
 * One unit's card (ADR-072, slice 5e): its pictures — the first one large,
 * each opening in our large copy — its name, town and how many people it
 * takes, its description, all it has, „od X zł / noc”, and under them the
 * application's calendar of its free days with the way to the form. On the
 * unit's own page (`main`) the name is the page's heading. Plain markup from
 * the server's answer; the editor shows where the card will be.
 */
export function StayUnitBlock({
  data,
  editor,
  imageRenderer,
  live,
  options,
}: BlockComponentProps) {
  const block = data as StayUnitV1Data;
  const locale = options?.locale ?? "pl";
  const texts = siteUiTexts(locale).stay;
  const shown = live?.data as StayLive | undefined;
  const unit = shown?.unit;
  const label = block.action_label || texts.checkDates;
  if (!shown || !unit)
    return h(
      "section",
      {
        className: "site-block site-block--stay-unit",
        "data-block-type": "core.stay_unit",
      },
      h(
        "div",
        { className: "site-stay__preview" },
        h(
          "div",
          {
            className: "site-stay-card site-stay-card--sample",
            "aria-hidden": true,
          },
          h("div", { className: "site-stay-card__gallery" }),
          h(
            "div",
            { className: "site-stay-card__body" },
            h("span", { className: "site-stay-unit__line" }),
            h("span", { className: "site-stay-unit__line" }),
            h("span", { className: "site-stay-unit__line" }),
          ),
        ),
        h(
          "span",
          { className: "site-section__action" },
          editor && block.action_label
            ? editor.text(["action_label"], block.action_label)
            : label,
        ),
        previewNote(texts.preview.unit),
      ),
    );
  const photos = unit.photos ?? [];
  const amenities = unit.amenities ?? [];
  const facts = [
    unit.town?.name,
    unit.capacity ? texts.capacity(unit.capacity) : undefined,
  ].filter(Boolean);
  const offer = shown.offers[0];
  return h(
    "section",
    {
      className: "site-block site-block--stay-unit",
      "data-block-type": "core.stay_unit",
    },
    h(
      "div",
      { className: "site-stay-card" },
      photos.length
        ? h(
            "div",
            { className: "site-stay-card__gallery" },
            ...photos.map((photo, index) =>
              h(
                "a",
                {
                  key: photo,
                  className: "site-stay-card__photo",
                  href: `/media/${photo}/preview`,
                  target: "_blank",
                  rel: "noopener",
                },
                unitPhoto(
                  photo,
                  texts.photo(unit.name, index + 1),
                  index === 0
                    ? "(min-width: 64rem) 55vw, 100vw"
                    : "(min-width: 48rem) 20vw, 33vw",
                  imageRenderer,
                ),
              ),
            ),
          )
        : null,
      h(
        "div",
        { className: "site-stay-card__body" },
        h(block.main ? "h1" : "h2", spoken(unit.lang, locale), unit.name),
        facts.length
          ? h("p", { className: "site-stay-unit__facts" }, facts.join(" · "))
          : null,
        unit.description
          ? h(
              "p",
              {
                className: "site-stay-unit__text",
                ...spoken(unit.description_lang, locale),
              },
              unit.description,
            )
          : null,
        amenities.length
          ? h(
              "ul",
              { className: "site-stay-unit__amenities" },
              ...amenities.map((item) =>
                h("li", { key: item.key }, item.label),
              ),
            )
          : null,
        unit.from_price
          ? fromPrice(unit.from_price, shown, texts, locale)
          : null,
        approxNote(shown, [unit.from_price], texts, locale),
      ),
    ),
    h(
      "div",
      { className: "site-stay__body" },
      live?.render?.("core.stay_unit", data, live.data) ??
        h(
          "a",
          {
            className: "site-section__action",
            href: stayFormHref(shown.form_url, {
              offer: offer?.id,
              choice: offer?.choices[0],
            }),
            rel: "nofollow",
          },
          label,
        ),
    ),
    otherUnits(shown.others, texts, locale, imageRenderer),
  );
}

/** Half the map's height in degrees: a few streets around a unit's own
 *  point, the whole town around its centre. */
const MAP_REACH = { exact: 0.004, town: 0.045 } as const;

/** Six decimals — a tenth of a metre — and no trailing noise in an address. */
const degrees = (value: number) => String(Number(value.toFixed(6)));

/** OpenStreetMap's own embeddable map of the place: a pin on a unit's own
 *  point, none on a town. No key and nothing of ours in the address but the
 *  place itself. */
export function stayMapEmbed(place: StayPlace): string {
  const tall = place.exact ? MAP_REACH.exact : MAP_REACH.town;
  // A degree east is shorter than a degree north by the latitude's cosine;
  // the frame is wider than tall.
  const wide =
    (tall * 1.8) / Math.max(Math.cos((place.latitude * Math.PI) / 180), 0.2);
  const query = new URLSearchParams({
    bbox: [
      place.longitude - wide,
      place.latitude - tall,
      place.longitude + wide,
      place.latitude + tall,
    ]
      .map(degrees)
      .join(","),
    layer: "mapnik",
  });
  if (place.exact)
    query.set(
      "marker",
      `${degrees(place.latitude)},${degrees(place.longitude)}`,
    );
  return `https://www.openstreetmap.org/export/embed.html?${query}`;
}

/** The same place on the map itself, for „Otwórz w mapach”. */
export function stayMapLink(place: StayPlace): string {
  const [north, east] = [degrees(place.latitude), degrees(place.longitude)];
  return place.exact
    ? `https://www.openstreetmap.org/?mlat=${north}&mlon=${east}#map=16/${north}/${east}`
    : `https://www.openstreetmap.org/#map=12/${north}/${east}`;
}

/**
 * Where a unit is (ADR-072, the map block of slice 5e): the unit's name and
 * town, and a map the visitor asks for. The place is the server's answer —
 * the town's centre, or the unit's own point once the company shows it. The
 * map is OpenStreetMap's and loads only after „Pokaż mapę” (the
 * application's component); the link to the map itself is plain markup and
 * is there without it. No answer — no section.
 */
export function StayMapBlock({
  data,
  editor,
  imageRenderer,
  live,
  options,
}: BlockComponentProps) {
  const block = data as StayMapV1Data;
  const locale = options?.locale ?? "pl";
  const texts = siteUiTexts(locale).stay;
  const shown = live?.data as StayMapLive | undefined;
  const place = shown?.place;
  const text = editor?.text ?? plainBlockText;
  const header = h(
    "div",
    { className: "site-section__intro" },
    h(
      "h2",
      editor ? { role: "presentation" } : null,
      block.title ? text(["title"], block.title) : texts.map.title,
    ),
    block.text
      ? h("p", { className: "site-section__lead" }, text(["text"], block.text))
      : null,
  );
  const section = {
    className: "site-block site-block--stay-map",
    "data-block-type": "core.stay_map",
  };
  if (!place)
    return h(
      "section",
      section,
      header,
      h(
        "div",
        { className: "site-stay__preview" },
        h(
          "div",
          { className: "site-stay-map__cover", "aria-hidden": true },
          h("span", { className: "site-section__action" }, texts.map.show),
        ),
        previewNote(texts.preview.map),
      ),
    );
  const where = [place.name, place.town?.name].filter(Boolean).join(" · ");
  return h(
    "section",
    section,
    header,
    h(
      "div",
      { className: "site-stay__body" },
      h("p", { className: "site-stay-map__place" }, where),
      place.exact
        ? null
        : h("p", { className: "site-stay-map__note" }, texts.map.townOnly),
      live?.render?.("core.stay_map", data, live.data) ??
        h(
          "p",
          { className: "site-stay-map__links" },
          h(
            "a",
            {
              href: stayMapLink(place),
              target: "_blank",
              rel: "noopener noreferrer",
            },
            texts.map.open,
          ),
        ),
    ),
    otherUnits(shown?.others, texts, locale, imageRenderer),
  );
}
