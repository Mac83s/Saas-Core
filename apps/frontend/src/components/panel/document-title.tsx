"use client";

import { useEffect } from "react";

/**
 * The browser tab says which page and which company (UX-084, WCAG 2.4.2):
 * „Kalendarz · Studio Testowe”, „Gospodarstwo Kowalski · Korekcja Racic Test”.
 * The page's own heading is the name — the same words the menu and the page
 * show (R1) — so a page that loads its record names the tab once it is there.
 */
export function PanelDocumentTitle({ company }: { company: string }) {
  useEffect(() => {
    const main = document.getElementById("panel-main");
    if (!main) return;
    const name = () => {
      const heading = main.querySelector("h1")?.textContent;
      // As `document.title` reads back: whitespace collapsed, none at the
      // ends. Without a company (an operator, or no active company yet) the
      // name is the heading alone — a title the getter gives back changed
      // would be set again on every mutation it causes, forever.
      const wanted = [heading, company]
        .map((part) => (part ?? "").replace(/\s+/g, " ").trim())
        .filter(Boolean)
        .join(" · ");
      if (document.title !== wanted) document.title = wanted;
    };
    name();
    // The heading arrives with the page's data, and a navigation sets the
    // product's own title again: both are answered.
    const content = new MutationObserver(name);
    content.observe(main, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    const head = new MutationObserver(name);
    head.observe(document.head, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    return () => {
      content.disconnect();
      head.disconnect();
    };
  }, [company]);
  return null;
}
