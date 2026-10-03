import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, test, vi } from "vitest";

import messages from "../../../../messages/pl.json";
import { TranslationFields } from "./translation-fields";

test("each unit shows its source, its field, its state and who wrote it", () => {
  const onChange = vi.fn();
  render(
    <NextIntlClientProvider locale="pl" messages={messages}>
      <TranslationFields
        idPrefix="t"
        labelFor={(key) => (key === "name" ? "Nazwa" : "Opis")}
        multiline={(key) => key === "description"}
        onChange={onChange}
        units={[
          {
            key: "name",
            source_text: "Strzyżenie",
            text: "Haarschnitt",
            status: "fresh",
            origin: "ai",
          },
          {
            key: "description",
            source_text: "Krótko",
            text: "",
            status: "stale",
            origin: "human",
          },
        ]}
        values={{ name: "Haarschnitt", description: "" }}
      />
    </NextIntlClientProvider>,
  );
  expect(screen.getByText("Strzyżenie")).not.toBeNull();
  expect(screen.getByText("Aktualne")).not.toBeNull();
  expect(screen.getByText("Tłumaczenie AI")).not.toBeNull();
  expect(screen.getByText("Do odświeżenia")).not.toBeNull();
  expect(screen.getByLabelText("Opis").tagName).toBe("TEXTAREA");
  fireEvent.change(screen.getByLabelText("Nazwa"), {
    target: { value: "Schnitt" },
  });
  expect(onChange).toHaveBeenCalledWith("name", "Schnitt");
});
