import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { PanelDocumentTitle } from "./document-title";

afterEach(cleanup);

test("the tab is named after the page's heading and the company", async () => {
  document.title = "HoofCare";
  const { rerender } = render(
    <>
      <PanelDocumentTitle company="Studio Testowe" />
      <main id="panel-main">
        <h1>Kalendarz</h1>
      </main>
    </>,
  );
  await waitFor(() =>
    expect(document.title).toBe("Kalendarz · Studio Testowe"),
  );
  // A record's page names the tab once its data is there.
  rerender(
    <>
      <PanelDocumentTitle company="Studio Testowe" />
      <main id="panel-main">
        <h1>Gospodarstwo Kowalski</h1>
      </main>
    </>,
  );
  await waitFor(() =>
    expect(document.title).toBe("Gospodarstwo Kowalski · Studio Testowe"),
  );
});

test("without a company the tab is the heading alone, and the name settles", async () => {
  document.title = "SaaS Core";
  const writes: string[] = [];
  const title =
    document.querySelector("title") ?? document.createElement("title");
  if (!title.isConnected) document.head.append(title);
  const observer = new MutationObserver(() => writes.push(document.title));
  observer.observe(document.head, { childList: true, subtree: true });
  render(
    <>
      <PanelDocumentTitle company="" />
      <main id="panel-main">
        <h1>
          Ustawienia
          {"\n   "}
          platformy
        </h1>
      </main>
    </>,
  );
  await waitFor(() => expect(document.title).toBe("Ustawienia platformy"));
  // The getter trims and collapses whitespace: a wanted name that differs
  // from what it gives back used to be written again without end.
  await new Promise((resolve) => setTimeout(resolve, 50));
  observer.disconnect();
  expect(writes.length).toBeLessThan(5);
});
