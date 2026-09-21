import { useState } from "react";
import axe from "axe-core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, test, vi } from "vitest";

import {
  sectionDecorationPresets,
  type SectionDecorationV1,
} from "@saas-core/site-blocks";
import polishMessages from "../../../../messages/pl.json";
import englishMessages from "../../../../messages/en.json";
import { SectionDecorationFields } from "./section-decoration-fields";

afterEach(cleanup);

function renderFields({
  locale = "pl",
  initial,
  disabled = false,
  onChange = vi.fn(),
  onSubmit = vi.fn(),
}: {
  locale?: "pl" | "en";
  initial?: SectionDecorationV1;
  disabled?: boolean;
  onChange?: ReturnType<typeof vi.fn>;
  onSubmit?: ReturnType<typeof vi.fn>;
} = {}) {
  function Form() {
    const [value, setValue] = useState(initial);
    return (
      <form
        aria-label="Existing block form"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <SectionDecorationFields
          value={value}
          disabled={disabled}
          onChange={(next) => {
            setValue(next);
            onChange(next);
          }}
        />
      </form>
    );
  }
  return {
    ...render(
      <NextIntlClientProvider
        locale={locale}
        messages={locale === "pl" ? polishMessages : englishMessages}
      >
        <Form />
      </NextIntlClientProvider>,
    ),
    onChange,
    onSubmit,
  };
}

test.each(["pl", "en"] as const)(
  "pola %s mają etykiety, grupy i dostępny opis ruchu bez zagnieżdżania formularzy",
  async (locale) => {
    const { container } = renderFields({ locale });
    expect(container.querySelectorAll("form")).toHaveLength(1);
    expect(screen.getAllByRole("combobox")).toHaveLength(7);
    const motion = screen.getByRole("combobox", {
      name: locale === "pl" ? "Animacja ozdobników" : "Ornament animation",
    });
    expect(motion).toBeDisabled();
    expect(motion).toHaveAccessibleDescription(
      locale === "pl"
        ? /Wybierz ozdobnik.*ograniczenia animacji/
        : /Choose an ornament.*reduced motion/,
    );
    for (const name of locale === "pl"
      ? ["Tło", "Ramka", "Ozdobniki", "Ruch"]
      : ["Background", "Border", "Ornaments", "Motion"]) {
      expect(screen.getByRole("group", { name })).not.toBeNull();
    }
    expect(
      screen.getByRole("button", {
        name: locale === "pl" ? "Usuń dekoracje" : "Remove decorations",
      }),
    ).toBeDisabled();
    expect((await axe.run(container)).violations).toHaveLength(0);
  },
);

test("zmienia jedno ustawienie i zachowuje pozostałe właściwości dekoracji", () => {
  const initial: SectionDecorationV1 = {
    schemaVersion: 1,
    frame: "accent",
    ornament: "rings",
    placement: "both",
    motion: "breathe",
  };
  const { onChange } = renderFields({ initial });
  fireEvent.change(screen.getByRole("combobox", { name: "Styl tła" }), {
    target: { value: "gradient" },
  });
  expect(onChange).toHaveBeenLastCalledWith({
    ...initial,
    background: "gradient",
  });
  fireEvent.change(
    screen.getByRole("combobox", { name: "Widoczność dekoracji" }),
    { target: { value: "soft" } },
  );
  expect(onChange).toHaveBeenLastCalledWith({
    ...initial,
    background: "gradient",
    intensity: "soft",
  });
  expect(initial).not.toHaveProperty("background");
  expect(screen.getByRole("combobox", { name: "Styl ramki" })).toHaveValue(
    "accent",
  );
});

test("pierwsza zmiana tworzy wersjonowaną dekorację bez materializowania niezmienianych wartości", () => {
  const { onChange } = renderFields();
  fireEvent.change(screen.getByRole("combobox", { name: "Styl ramki" }), {
    target: { value: "double" },
  });
  expect(onChange).toHaveBeenCalledExactlyOnceWith({
    schemaVersion: 1,
    frame: "double",
  });
});

test("wyłącza ruch przy braku ozdobnika i przywraca go bez utraty ustawienia", () => {
  const { onChange } = renderFields({
    initial: { schemaVersion: 1, ornament: "orbs", motion: "drift" },
  });
  const motion = screen.getByRole("combobox", { name: "Animacja ozdobników" });
  expect(motion).not.toBeDisabled();
  fireEvent.change(
    screen.getByRole("combobox", { name: "Rodzaj ozdobników" }),
    { target: { value: "none" } },
  );
  expect(motion).toBeDisabled();
  expect(motion).toHaveValue("drift");
  expect(onChange).toHaveBeenLastCalledWith({
    schemaVersion: 1,
    ornament: "none",
    motion: "drift",
  });
  fireEvent.change(motion, { target: { value: "breathe" } });
  expect(onChange).toHaveBeenCalledTimes(1);
  fireEvent.change(
    screen.getByRole("combobox", { name: "Rodzaj ozdobników" }),
    { target: { value: "wave" } },
  );
  expect(motion).not.toBeDisabled();
  expect(motion).toHaveValue("drift");
});

test.each(["pl", "en"] as const)(
  "wybiera gotowy styl %s jako kopię i pokazuje jego opis",
  (locale) => {
    const preset = sectionDecorationPresets[0];
    expect(preset).toBeDefined();
    const { onChange } = renderFields({ locale });
    const select = screen.getByRole("combobox", {
      name: locale === "pl" ? "Gotowy styl" : "Ready-made style",
    });
    fireEvent.change(select, { target: { value: preset.id } });
    expect(onChange).toHaveBeenLastCalledWith(preset.decoration);
    expect(onChange.mock.calls[0][0]).not.toBe(preset.decoration);
    expect(select).toHaveValue(preset.id);
    expect(select).toHaveAccessibleDescription(
      preset.labels[locale].description,
    );
  },
);

test("przywraca domyślny wygląd, usuwając override, bez zapisu zewnętrznego formularza", () => {
  const { onChange, onSubmit } = renderFields({
    initial: { schemaVersion: 1, background: "dots", ornament: "botanical" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Usuń dekoracje" }));
  expect(onChange).toHaveBeenCalledExactlyOnceWith(undefined);
  expect(onSubmit).not.toHaveBeenCalled();
  expect(screen.getByRole("combobox", { name: "Styl tła" })).toHaveValue(
    "none",
  );
  expect(
    screen.getByRole("combobox", { name: "Rodzaj ozdobników" }),
  ).toHaveValue("none");
  expect(
    screen.getByText("Ta sekcja korzysta z domyślnego wyglądu szablonu."),
  ).not.toBeNull();
});

test("blokuje wszystkie edycje podczas zapisu i odrzuca nieznane wartości", () => {
  const { onChange, unmount } = renderFields({
    initial: { schemaVersion: 1, ornament: "orbs" },
    disabled: true,
  });
  for (const select of screen.getAllByRole("combobox"))
    expect(select).toBeDisabled();
  fireEvent.change(screen.getByRole("combobox", { name: "Styl tła" }), {
    target: { value: "grid" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Gotowy styl" }), {
    target: { value: sectionDecorationPresets[0].id },
  });
  fireEvent.click(screen.getByRole("button", { name: "Usuń dekoracje" }));
  expect(onChange).not.toHaveBeenCalled();
  unmount();
  renderFields({ onChange });
  fireEvent.change(screen.getByRole("combobox", { name: "Styl tła" }), {
    target: { value: "arbitrary-css" },
  });
  expect(onChange).not.toHaveBeenCalled();
});
