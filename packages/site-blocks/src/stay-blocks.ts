import { createElement as h, type ReactNode } from "react";

import { plainBlockText } from "./block-text";
import { siteUiTexts, type StayTexts } from "./site-ui-texts";
import type {
  BlockComponentProps,
  StayBlockV1Data,
  StayLive,
  StayLiveChoice,
  StayLiveOffer,
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

/** One picture of a unit at the site's own host: our two copies, never the
 *  original — as the company's form serves it. */
function unitPhoto(assetId: string, alt: string, sizes: string) {
  const base = `/media/${assetId}`;
  return h("img", {
    src: `${base}/preview`,
    srcSet: `${base}/thumbnail 320w, ${base}/preview 1280w`,
    sizes,
    alt,
    loading: "lazy",
    decoding: "async",
  });
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
          unitPhoto(cover, choice.name, sizes),
        )
      : null,
    h(
      "div",
      { className: "site-stay-unit__body" },
      h(heading, { className: "site-stay-unit__name" }, choice.name),
      facts.length
        ? h("p", { className: "site-stay-unit__facts" }, facts.join(" · "))
        : null,
      choice.description
        ? h("p", { className: "site-stay-unit__text" }, choice.description)
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
          ? h(
              "p",
              { className: "site-stay-unit__price" },
              texts.fromPrice(
                stayAmount(choice.from_price, locale),
                choice.from_price.per,
              ),
            )
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
        ),
      ),
    );
  return h(
    "section",
    {
      className: `site-block site-block--stay-units site-stay-units--${layout}`,
      "data-block-type": "core.stay_units",
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
                    editor && block.action_label
                      ? editor.text(["action_label"], block.action_label)
                      : actionLabel,
                  ),
                ),
              ),
            ),
          ),
          previewNote(texts.preview.units),
        ),
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
