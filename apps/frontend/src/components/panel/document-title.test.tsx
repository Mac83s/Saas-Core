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
