"use client";

import { useEffect, useRef, useState } from "react";

import {
  siteUiTexts,
  stayMapEmbed,
  stayMapLink,
  type StayPlace,
} from "@saas-core/site-blocks";

/**
 * The map of where a unit is, on a company's own site (ADR-072, the map
 * block of slice 5e). OpenStreetMap draws it, so nothing of it is asked for
 * until the visitor says „Pokaż mapę”: before that click their browser has
 * talked to this site only. The frame then loads without a referrer, in a
 * sandbox, and the way out to the map itself is a plain link that is there
 * from the start. The place is the server's answer for the block: a town's
 * centre, or the unit's own point when the company shows it.
 */
export function SiteStayMap({
  locale,
  place,
}: {
  /** The page's language; the words come from the site's catalogue. */
  locale: string;
  place: StayPlace;
}) {
  const texts = siteUiTexts(locale).stay.map;
  const [shown, setShown] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null);
  // The button that was pressed is gone: the map takes its place and the
  // focus, so a keyboard does not start again from the top of the page.
  useEffect(() => {
    if (shown) frame.current?.focus();
  }, [shown]);
  const where = [place.name, place.town?.name].filter(Boolean).join(", ");
  return (
    <div className="site-stay-map">
      {shown ? (
        <iframe
          className="site-stay-map__frame"
          loading="lazy"
          ref={frame}
          referrerPolicy="no-referrer"
          sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"
          src={stayMapEmbed(place)}
          title={texts.frame(where)}
        />
      ) : (
        <div className="site-stay-map__cover">
          <button
            className="site-section__action"
            onClick={() => setShown(true)}
            type="button"
          >
            {texts.show}
          </button>
          <p className="site-stay-map__notice">{texts.notice}</p>
        </div>
      )}
      <p className="site-stay-map__links">
        <a href={stayMapLink(place)} rel="noopener noreferrer" target="_blank">
          {texts.open}
        </a>
      </p>
    </div>
  );
}
