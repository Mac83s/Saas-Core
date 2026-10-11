"use client";

/** Where the menu offers „Treści”, the blog is one content type among the
 *  site's (ADR-079 pkt 25) and has one screen: its type screen. The old
 *  address `/panel/sites/blog` — a bookmark, a link from the translation
 *  centre, an assistant's message — leads there, `?entry=` with it. Where the
 *  menu says „Blog” the address stays the blog's own screen, so the caller
 *  renders `fallback` there and never mounts this. */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import { listContentCollections } from "@saas-core/api-client";

import { ENTRY_PARAM } from "./entry-param";
import { contentTypeHref, contentTypesHref } from "./content-types-panel";

export function BlogRedirect({
  siteId,
  onGo,
  fallback,
}: {
  siteId: string;
  /** Replaces this address (not a new history entry: Back must not return
   *  to a screen that only forwards). */
  onGo: (href: string) => void;
  /** What shows when the site's types cannot be read: the blog screen itself. */
  fallback: ReactNode;
}) {
  const t = useTranslations("Sites.contentTypes");
  const [failed, setFailed] = useState(false);
  // The caller's callback changes identity with every render of the page;
  // asking the site again for that would loop.
  const go = useRef(onGo);
  useEffect(() => {
    go.current = onGo;
  }, [onGo]);

  useEffect(() => {
    let current = true;
    listContentCollections(siteId)
      .then((all) => {
        if (!current) return;
        // The one the blog screen showed: the first that is switched on.
        const first = all.find((item) => !item.archived);
        if (!first) {
          // Nothing yet: the list is where the first one is made.
          go.current(contentTypesHref(siteId));
          return;
        }
        const entry = new URLSearchParams(globalThis.location?.search).get(
          ENTRY_PARAM,
        );
        go.current(
          `${contentTypeHref(siteId, first.id)}${
            entry ? `&${ENTRY_PARAM}=${encodeURIComponent(entry)}` : ""
          }`,
        );
      })
      .catch(() => {
        if (current) setFailed(true);
      });
    return () => {
      current = false;
    };
  }, [siteId]);

  if (failed) return fallback;
  return (
    <p className="text-sm text-muted-foreground" role="status">
      {t("blogMoved")}
    </p>
  );
}
