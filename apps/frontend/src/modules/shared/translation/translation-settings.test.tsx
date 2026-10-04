import axe from "axe-core";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, test, vi } from "vitest";

import {
  ApiProblemError,
  type GlossaryTerm,
  type TranslationOffer,
  type TranslationSettings,
} from "@saas-core/api-client";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { TranslationSettingsSection } from "./translation-settings";

const { api } = vi.hoisted(() => ({
  api: {
    getTranslationOffer: vi.fn(),
    getTranslationSettings: vi.fn(),
    updateTranslationSettings: vi.fn(),
    listGlossaryTerms: vi.fn(),
    createGlossaryTerm: vi.fn(),
    updateGlossaryTerm: vi.fn(),
    deleteGlossaryTerm: vi.fn(),
    getPublicLocales: vi.fn(),
  },
}));
// These screens ask the translation engine: the deployment composes it here.
vi.mock("../../../generated/deployment", async (original) =>
  (await import("./testing")).withTranslationEngine(original),
);
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));

const MODE = "translation.settings.mode";
const AUTO = "translation.settings.auto_changes";
const LIMIT = "translation.settings.auto_monthly_limit";

type Value = TranslationSettings["values"][string];
const value = (overrides: Partial<Value>): Value => ({
  value: null,
  effective: null,
  source: "code",
  locked: false,
  lock_reason: null,
  operator_reason: null,
  ...overrides,
});

function settings(
  overrides: Partial<TranslationSettings> = {},
  values: Record<string, Partial<Value>> = {},
): TranslationSettings {
  return {
    group: "translation.settings",
    version: 3,
    values: {
      [MODE]: value({ effective: "automatic", ...values[MODE] }),
      [AUTO]: value({ effective: false, ...values[AUTO] }),
      [LIMIT]: value({ effective: 100, ...values[LIMIT] }),
    },
    automation: {
      consent_membership_id: null,
      consent_at: null,
      consent_name: null,
      consent_holds: false,
      month_credits: 0,
      month_resets_at: "2026-10-31T23:00:00Z",
    },
    processing_acknowledged: true,
    processing_ack_at: "2026-10-01T10:00:00Z",
    ...overrides,
  };
}

const RUNNING = settings(
  {
    automation: {
      consent_membership_id: "0199f0a0-0000-7000-8000-0000000000f1",
      consent_at: "2026-10-03T10:00:00Z",
      consent_name: "Ada Nowak",
      consent_holds: true,
      month_credits: 12,
      month_resets_at: "2026-10-31T23:00:00Z",
    },
  },
  {
    [AUTO]: { value: true, effective: true, source: "organization" },
    [LIMIT]: { value: 50, effective: 50, source: "organization" },
  },
);

const OFFER = {
  available: true,
  reasons: [],
  billing: {
    mode: "credits",
    operation_key: "translation.characters",
    unit_characters: 1000,
    credits_per_unit: 1,
  },
  glossary_limit: 500,
  settings: [
    {
      key: MODE,
      type: "enum",
      default: "automatic",
      minimum: null,
      maximum: null,
      values: [
        {
          value: "automatic",
          label: { pl: "Automatycznie", en: "Automatically" },
        },
        {
          value: "review",
          label: { pl: "Po akceptacji", en: "After approval" },
        },
      ],
      label: { pl: "Publikacja tłumaczeń", en: "Publishing translations" },
      help: null,
    },
    {
      key: AUTO,
      type: "bool",
      default: false,
      minimum: null,
      maximum: null,
      values: null,
      label: {
        pl: "Tłumacz zmiany automatycznie",
        en: "Translate changes automatically",
      },
      help: {
        pl: "Po zmianie opublikowanej treści jej tłumaczenia odświeżą się same.",
        en: "When published content changes, its translations refresh themselves.",
      },
    },
    {
      key: LIMIT,
      type: "int",
      default: 100,
      minimum: 0,
      maximum: 100000,
      values: null,
      label: {
        pl: "Miesięczny limit automatu",
        en: "Monthly limit of the automation",
      },
      help: { pl: "0 wyłącza automat.", en: "0 turns the automation off." },
    },
  ],
} as unknown as TranslationOffer;

function term(overrides: Partial<GlossaryTerm> = {}): GlossaryTerm {
  return {
    id: "0199f0a0-0000-7000-8000-0000000000c1",
    term: "Studio Alfa",
    rule: "keep",
    source_locale: "pl",
    target_locale: "",
    translation: "",
    forms: ["Studia Alfa"],
    version: 2,
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-01T10:00:00Z",
    ...overrides,
  };
}

function problem(
  status: number,
  code: string,
  errors?: { field: string; code: string; message: string }[],
) {
  return new ApiProblemError({
    type: "about:blank",
    title: "Problem",
    status,
    code,
    detail: "",
    errors,
  } as ConstructorParameters<typeof ApiProblemError>[0]);
}

function view(canManage = true, locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <TranslationSettingsSection canManage={canManage} />
    </NextIntlClientProvider>,
  );
}

async function expectNoAxeViolations(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(
    results.violations.map((violation) => violation.id),
    JSON.stringify(results.violations, null, 2),
  ).toEqual([]);
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getTranslationOffer.mockResolvedValue(OFFER);
  api.getTranslationSettings.mockResolvedValue(settings());
  api.listGlossaryTerms.mockResolvedValue({ items: [], next_cursor: null });
  api.getPublicLocales.mockResolvedValue({
    public_locales: ["pl", "en", "de"],
    offered: [
      { code: "pl", native_name: "polski" },
      { code: "en", native_name: "English" },
      { code: "de", native_name: "Deutsch" },
    ],
    protected: {},
    version: 1,
    limit: null,
  });
});

test("shows the mode, the automation with its consent and the month's usage, and the glossary", async () => {
  api.getTranslationSettings.mockResolvedValue(RUNNING);
  api.listGlossaryTerms.mockResolvedValue({
    items: [
      term(),
      term({
        id: "0199f0a0-0000-7000-8000-0000000000c2",
        term: "strzyżenie",
        rule: "translate_as",
        target_locale: "en",
        translation: "grooming",
        forms: [],
      }),
    ],
    next_cursor: null,
  });
  const { container } = view();

  const modes = await screen.findByRole("radiogroup", {
    name: "Publikacja tłumaczeń",
  });
  expect(
    within(modes)
      .getByRole("radio", { name: /Automatycznie/ })
      .getAttribute("aria-checked"),
  ).toBe("true");
  expect(
    screen.getByText("Dokumenty prawne zawsze czekają na akceptację."),
  ).toBeTruthy();
  expect(
    screen
      .getByRole("switch", { name: "Tłumacz zmiany automatycznie" })
      .getAttribute("aria-checked"),
  ).toBe("true");
  expect(
    screen.getByText(
      "Działa w imieniu: Ada Nowak — zgoda z 3 października 2026.",
    ),
  ).toBeTruthy();
  expect(
    (screen.getByLabelText("Miesięczny limit automatu") as HTMLInputElement)
      .value,
  ).toBe("50");
  const usage = screen.getByText(
    "W tym miesiącu automat wykorzystał 12 z 50 kredytów.",
  );
  const bar = screen.getByRole("progressbar");
  expect(bar.getAttribute("aria-labelledby")).toBe(usage.id);
  expect(bar.getAttribute("aria-valuenow")).toBe("12");
  expect(bar.getAttribute("aria-valuemax")).toBe("50");
  expect(
    screen.getByText("Licznik zaczyna się od nowa 1 listopada 2026."),
  ).toBeTruthy();
  expect(
    screen.getByText(/Firma potwierdziła 1 października 2026/),
  ).toBeTruthy();

  const table = await screen.findByRole("table", {
    name: "Terminy glosariusza",
  });
  const [keep, translated] = within(table).getAllByRole("row").slice(1);
  expect(keep!.textContent).toContain("Studio Alfa");
  expect(keep!.textContent).toContain("Odmiany: Studia Alfa");
  expect(keep!.textContent).toContain("Zostawia bez zmian");
  expect(keep!.textContent).toContain("Polski → wszystkie języki");
  expect(translated!.textContent).toContain("Tłumaczy jako „grooming”");
  expect(translated!.textContent).toContain("Polski → English");
  // Nothing was changed: nothing to save yet.
  expect(
    (screen.getByRole("button", { name: "Zapisz zmiany" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  await expectNoAxeViolations(container);
});

test("English words and axe", async () => {
  api.getTranslationSettings.mockResolvedValue(RUNNING);
  api.listGlossaryTerms.mockResolvedValue({
    items: [term()],
    next_cursor: null,
  });
  const { container } = view(true, "en");
  expect(
    await screen.findByRole("radiogroup", { name: "Publishing translations" }),
  ).toBeTruthy();
  expect(
    screen.getByText("This month the automation has used 12 of 50 credits."),
  ).toBeTruthy();
  expect(
    screen.getByText(
      "Acts on behalf of: Ada Nowak — consent of October 3, 2026.",
    ),
  ).toBeTruthy();
  expect(await screen.findByText("Keeps it unchanged")).toBeTruthy();
  await expectNoAxeViolations(container);
});

test("a changed mode and limit are saved at the version on screen, only what changed", async () => {
  api.updateTranslationSettings.mockResolvedValue(
    settings(
      { version: 4 },
      {
        [MODE]: {
          value: "review",
          effective: "review",
          source: "organization",
        },
        [LIMIT]: { value: 20, effective: 20, source: "organization" },
      },
    ),
  );
  view();
  fireEvent.click(await screen.findByRole("radio", { name: /Po akceptacji/ }));
  fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
  await waitFor(() =>
    expect(api.updateTranslationSettings).toHaveBeenCalledWith(
      { mode: "review" },
      3,
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText("Zapisano ustawienia tłumaczeń."),
  ).toBeTruthy();
  expect(screen.getAllByText("Ustawione dla firmy").length).toBe(2);

  // A limit out of bounds is refused before it is sent.
  const limit = screen.getByLabelText("Miesięczny limit automatu");
  fireEvent.change(limit, { target: { value: "-5" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
  expect(
    await screen.findByText("Podaj liczbę całkowitą od 0 do 100 000."),
  ).toBeTruthy();
  expect(api.updateTranslationSettings).toHaveBeenCalledTimes(1);

  // „Przywróć domyślne” sends the key back to the inherited value.
  fireEvent.click(
    screen.getAllByRole("button", { name: "Przywróć domyślne" })[0]!,
  );
  fireEvent.change(limit, { target: { value: "30" } });
  fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
  await waitFor(() =>
    expect(api.updateTranslationSettings).toHaveBeenLastCalledWith(
      { auto_monthly_limit: 30, reset: [MODE] },
      4,
      expect.any(String),
    ),
  );
});

test("turning the automation on is a consent with the price and the limit on screen", async () => {
  api.getTranslationSettings.mockResolvedValue(
    settings({ processing_acknowledged: false, processing_ack_at: null }),
  );
  api.updateTranslationSettings.mockResolvedValue(RUNNING);
  view();
  fireEvent.click(
    await screen.findByRole("switch", { name: "Tłumacz zmiany automatycznie" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Włączyć automatyczne tłumaczenie zmian?",
  });
  expect(dialog.textContent).toContain(
    "Cena: 1 kredyt za 1000 znaków tekstu w jednym języku.",
  );
  expect(dialog.textContent).toContain(
    "Limit: najwyżej 100 kredytów miesięcznie.",
  );
  expect(dialog.textContent).toContain("To Twoja zgoda");
  expect(api.updateTranslationSettings).not.toHaveBeenCalled();

  // The company has not confirmed where content goes: the consent asks for it.
  const confirm = within(dialog).getByRole("button", {
    name: "Włącz i wyraź zgodę",
  }) as HTMLButtonElement;
  expect(confirm.disabled).toBe(true);
  fireEvent.click(
    within(dialog).getByRole("checkbox", { name: /trafia do OpenRouter/ }),
  );
  fireEvent.click(confirm);
  await waitFor(() =>
    expect(api.updateTranslationSettings).toHaveBeenCalledWith(
      { auto_changes: true, processing_acknowledged: true },
      3,
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText(
      "Automatyczne tłumaczenie zmian jest włączone. Działa w Twoim imieniu.",
    ),
  ).toBeTruthy();
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  // Turning it off needs no question.
  api.updateTranslationSettings.mockResolvedValue(settings());
  fireEvent.click(
    screen.getByRole("switch", { name: "Tłumacz zmiany automatycznie" }),
  );
  await waitFor(() =>
    expect(api.updateTranslationSettings).toHaveBeenLastCalledWith(
      { auto_changes: false },
      3,
      expect.any(String),
    ),
  );
});

test("a consent that no longer holds stops the automation until somebody confirms again", async () => {
  api.getTranslationSettings.mockResolvedValue({
    ...RUNNING,
    automation: { ...RUNNING.automation, consent_holds: false },
  });
  api.updateTranslationSettings.mockRejectedValueOnce(
    problem(403, "person_required"),
  );
  view();
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain(
    "Automat stoi: Ada Nowak nie może już zarządzać tłumaczeniami",
  );
  fireEvent.click(
    within(alert).getByRole("button", { name: "Potwierdź ponownie" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Potwierdzić automat w swoim imieniu?",
  });
  // Already confirmed where content goes: no second statement.
  expect(within(dialog).queryByRole("checkbox")).toBeNull();
  fireEvent.click(within(dialog).getByRole("button", { name: "Potwierdzam" }));
  expect((await within(dialog).findByRole("alert")).textContent).toContain(
    "Tę decyzję podejmuje osoba",
  );

  api.updateTranslationSettings.mockResolvedValueOnce(RUNNING);
  fireEvent.click(within(dialog).getByRole("button", { name: "Potwierdzam" }));
  expect(
    await screen.findByText(
      "Potwierdzono. Automat działa teraz w Twoim imieniu.",
    ),
  ).toBeTruthy();
  const [first, second] = api.updateTranslationSettings.mock.calls;
  expect(first![0]).toEqual({ auto_changes: true });
  // What was refused is asked again as a new request.
  expect(second![2]).not.toBe(first![2]);
});

test("a value the operator decides is shown with the reason and cannot be changed", async () => {
  api.getTranslationSettings.mockResolvedValue(
    settings(
      {},
      {
        [MODE]: {
          value: "automatic",
          effective: "review",
          source: "operator",
          locked: true,
          lock_reason: "operator_forced_review",
          operator_reason: "Skargi na jakość",
        },
        [LIMIT]: {
          value: 80,
          effective: 40,
          source: "operator",
          locked: true,
          lock_reason: "operator_cap",
          operator_reason: "Okres próbny",
        },
      },
    ),
  );
  view();
  const review = await screen.findByRole("radio", { name: /Po akceptacji/ });
  expect(
    review.getAttribute("aria-disabled") ?? review.getAttribute("disabled"),
  ).not.toBeNull();
  expect(
    screen.getByText(/Teraz każde tłumaczenie czeka na akceptację/).textContent,
  ).toContain("Powód: Skargi na jakość");
  expect(
    screen.getByText(
      /Operator platformy ograniczył limit — teraz obowiązuje 40/,
    ).textContent,
  ).toContain("Powód: Okres próbny");
  expect(
    screen.getAllByText("Ustawione przez operatora platformy").length,
  ).toBe(2);
});

test("the one-off confirmation of processing is a ticked statement", async () => {
  api.getTranslationSettings.mockResolvedValue(
    settings({ processing_acknowledged: false, processing_ack_at: null }),
  );
  api.updateTranslationSettings.mockResolvedValue(settings());
  view();
  const confirm = (await screen.findByRole("button", {
    name: "Potwierdź",
  })) as HTMLButtonElement;
  expect(confirm.disabled).toBe(true);
  fireEvent.click(
    screen.getByRole("checkbox", { name: /trafia do OpenRouter/ }),
  );
  fireEvent.click(confirm);
  await waitFor(() =>
    expect(api.updateTranslationSettings).toHaveBeenCalledWith(
      { processing_acknowledged: true },
      3,
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText(
      "Potwierdzenie zapisane. Możesz zlecać tłumaczenia AI.",
    ),
  ).toBeTruthy();
});

test("somebody else's change meanwhile is said and the current settings are read again", async () => {
  api.updateTranslationSettings.mockRejectedValueOnce(
    problem(409, "translation_version_conflict"),
  );
  view();
  fireEvent.click(await screen.findByRole("radio", { name: /Po akceptacji/ }));
  api.getTranslationSettings.mockResolvedValue(settings({ version: 9 }));
  fireEvent.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Ktoś w międzyczasie zmienił te ustawienia",
  );
  await waitFor(() =>
    expect(api.getTranslationSettings).toHaveBeenCalledTimes(2),
  );
});

test("a reader without the right to manage sees the values and no way to change them", async () => {
  api.getTranslationSettings.mockResolvedValue(RUNNING);
  api.listGlossaryTerms.mockResolvedValue({
    items: [term()],
    next_cursor: null,
  });
  view(false);
  expect(
    await screen.findByText(
      "Te ustawienia zmienia administrator albo właściciel firmy.",
    ),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Zapisz zmiany" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Dodaj termin" })).toBeNull();
  expect(
    (screen.getByLabelText("Miesięczny limit automatu") as HTMLInputElement)
      .disabled,
  ).toBe(true);
  await screen.findByText("Studio Alfa");
  expect(
    screen.queryByRole("button", { name: /Edytuj: Studio Alfa/ }),
  ).toBeNull();
});

test("no section without a translation engine; a failed read offers another try", async () => {
  api.getTranslationOffer.mockRejectedValueOnce(new Error("no engine"));
  const absent = view();
  await waitFor(() => expect(api.getTranslationOffer).toHaveBeenCalled());
  expect(absent.container.textContent).toBe("");
  expect(api.getTranslationSettings).not.toHaveBeenCalled();
  absent.unmount();

  api.getTranslationSettings.mockRejectedValueOnce(new Error("down"));
  view();
  expect((await screen.findByRole("alert")).textContent).toContain(
    "Nie udało się wczytać ustawień tłumaczeń.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  expect(
    await screen.findByRole("radiogroup", { name: "Publikacja tłumaczeń" }),
  ).toBeTruthy();
});

test("a glossary term is added with its rule, languages and forms; the server's refusal lands on the field", async () => {
  view();
  fireEvent.click(await screen.findByRole("button", { name: "Dodaj termin" }));
  const dialog = await screen.findByRole("dialog", { name: "Nowy termin" });
  const save = within(dialog).getByRole("button", { name: "Dodaj termin" });

  // An empty term and a missing translation are caught before sending.
  fireEvent.change(within(dialog).getByLabelText("Co ma zrobić tłumaczenie"), {
    target: { value: "translate_as" },
  });
  fireEvent.click(save);
  expect(await within(dialog).findByText("Wpisz termin.")).toBeTruthy();
  expect(within(dialog).getByText("Podaj tłumaczenie terminu.")).toBeTruthy();
  expect(api.createGlossaryTerm).not.toHaveBeenCalled();

  fireEvent.change(within(dialog).getByLabelText("Termin"), {
    target: { value: "strzyżenie" },
  });
  fireEvent.change(within(dialog).getByLabelText("Tłumaczenie"), {
    target: { value: "grooming" },
  });
  fireEvent.change(within(dialog).getByLabelText("Dotyczy tłumaczeń na"), {
    target: { value: "en" },
  });
  fireEvent.change(within(dialog).getByLabelText("Odmiany terminu"), {
    target: { value: "strzyżenia\n\n strzyżeniu " },
  });
  api.createGlossaryTerm.mockRejectedValueOnce(
    problem(400, "validation_error", [
      { field: "term", code: "glossary_term_exists", message: "" },
    ]),
  );
  fireEvent.click(save);
  expect(
    await within(dialog).findByText(
      "Ten termin już jest w glosariuszu dla tych języków.",
    ),
  ).toBeTruthy();
  expect(api.createGlossaryTerm).toHaveBeenLastCalledWith(
    {
      term: "strzyżenie",
      rule: "translate_as",
      source_locale: "pl",
      target_locale: "en",
      translation: "grooming",
      forms: ["strzyżenia", "strzyżeniu"],
    },
    expect.any(String),
  );

  api.createGlossaryTerm.mockResolvedValueOnce(term({ term: "strzyżenie" }));
  fireEvent.click(save);
  expect(await screen.findByText("Dodano termin „strzyżenie”.")).toBeTruthy();
  await waitFor(() => expect(api.listGlossaryTerms).toHaveBeenCalledTimes(2));
});

test("a term is edited at its version and removed after a question; more terms come on request", async () => {
  api.listGlossaryTerms.mockResolvedValue({
    items: [term()],
    next_cursor: "100",
  });
  view();
  fireEvent.click(
    await screen.findByRole("button", { name: "Edytuj: Studio Alfa" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "Edytuj termin" });
  expect(
    (within(dialog).getByLabelText("Odmiany terminu") as HTMLTextAreaElement)
      .value,
  ).toBe("Studia Alfa");
  // „Zostaw bez zmian” has no translation to give.
  expect(within(dialog).queryByLabelText("Tłumaczenie")).toBeNull();
  fireEvent.change(within(dialog).getByLabelText("Termin"), {
    target: { value: "Studio Alfa Plus" },
  });
  api.updateGlossaryTerm.mockResolvedValueOnce(term());
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz termin" }),
  );
  await waitFor(() =>
    expect(api.updateGlossaryTerm).toHaveBeenCalledWith(
      term().id,
      {
        term: "Studio Alfa Plus",
        rule: "keep",
        source_locale: "pl",
        target_locale: "",
        translation: "",
        forms: ["Studia Alfa"],
      },
      2,
      expect.any(String),
    ),
  );
  expect(
    await screen.findByText("Zapisano termin „Studio Alfa Plus”."),
  ).toBeTruthy();

  api.listGlossaryTerms.mockResolvedValueOnce({
    items: [term({ id: "0199f0a0-0000-7000-8000-0000000000c9", term: "Beta" })],
    next_cursor: null,
  });
  fireEvent.click(
    await screen.findByRole("button", { name: "Wczytaj więcej" }),
  );
  expect(await screen.findByText("Beta")).toBeTruthy();
  expect(api.listGlossaryTerms).toHaveBeenLastCalledWith({
    limit: 100,
    cursor: "100",
  });

  fireEvent.click(
    screen.getByRole("button", { name: "Działania dla terminu Beta" }),
  );
  fireEvent.click(await screen.findByRole("menuitem", { name: "Usuń: Beta" }));
  const question = await screen.findByRole("dialog", {
    name: "Usunąć termin „Beta”?",
  });
  expect(api.deleteGlossaryTerm).not.toHaveBeenCalled();
  api.deleteGlossaryTerm.mockResolvedValueOnce(undefined);
  fireEvent.click(
    within(question).getByRole("button", { name: "Usuń termin" }),
  );
  await waitFor(() =>
    expect(api.deleteGlossaryTerm).toHaveBeenCalledWith(
      "0199f0a0-0000-7000-8000-0000000000c9",
      2,
      expect.any(String),
    ),
  );
  expect(await screen.findByText("Usunięto termin „Beta”.")).toBeTruthy();
});
