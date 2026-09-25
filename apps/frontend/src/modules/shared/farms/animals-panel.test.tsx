import axe from "axe-core";
import {
  cleanup,
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
  type Farm,
  type FarmAnimal,
} from "@saas-core/api-client";
import type { PanelAccess } from "#lib/panel-navigation";
import type { ProductAnimalSection } from "#lib/product-extension";
import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { AnimalsPanel } from "./animals-panel";

const { api, sections } = vi.hoisted(() => ({
  api: {
    createFarmAnimalHealth: vi.fn(),
    getFarmHealthPhoto: vi.fn(),
    listFarmAnimalHealth: vi.fn(),
    listFarmAnimals: vi.fn(),
    listFarms: vi.fn(),
    createFarmAnimal: vi.fn(),
    updateFarmAnimal: vi.fn(),
  },
  // The product slot is an array the card reads; a test fills it in place.
  sections: [] as ProductAnimalSection[],
}));
vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("../../../product/animal-sections", () => ({ default: sections }));
vi.mock("#i18n/navigation", () => ({
  Link: ({
    children,
    ...props
  }: React.ComponentProps<"a"> & { children: React.ReactNode }) => (
    <a {...props}>{children}</a>
  ),
}));

const FULL = ["farms.read", "farms.manage"];

function access(permissions: readonly string[] | null = FULL): PanelAccess {
  return {
    modules: ["shared.farms"],
    permissions,
    isOwner: false,
    limited: true,
    organizationType: "trimming_company",
  };
}

function farm(id: string, name: string): Farm {
  return {
    id,
    name,
    herd_number: "PL012345678001",
    tax_id: "",
    village: "Wólka",
    address: "",
    keeper_name: "",
    email: "",
    phone: "",
    housing: "",
    notes: "",
    active: true,
    animal_count: 2,
    updated_at: "2026-09-18T09:00:00Z",
  };
}

function animal(
  id: string,
  national_id: string,
  over: Partial<FarmAnimal> = {},
): FarmAnimal {
  return {
    id,
    farm_id: "farm-1",
    farm_name: "Nowakowie",
    species: "cattle",
    national_id,
    working_number: "",
    name: "",
    sex: "female",
    birth_date: null,
    status: "active",
    notes: "",
    review_requested_at: null,
    withdrawal_milk_until: null,
    withdrawal_meat_until: null,
    updated_at: "2026-09-18T09:00:00Z",
    ...over,
  };
}

const HERD = [
  animal("a1", "PL005432198765", { name: "Mućka", working_number: "412" }),
  animal("a2", "PL005432100001", { working_number: "77" }),
  animal("a3", "PL005432100002", {
    farm_id: "farm-2",
    farm_name: "Zagroda Lisów",
    status: "sold",
    birth_date: "2022-04-01",
    notes: "Sprzedana na targu.",
  }),
];

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom nie zna adresów blob; miniatura kartoteki ich używa, żeby bajty
  // cudzego zdjęcia nie trafiły do historii przeglądarki.
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = () => "blob:entry-photo";
      static revokeObjectURL = () => undefined;
    },
  );
  api.listFarmAnimalHealth.mockResolvedValue([
    {
      id: "h1",
      animal_id: "a3",
      kind: "treatment",
      occurred_on: "2026-09-18",
      source: "hoofcare.visit",
      source_reference: "visit-1",
      author_name: "Piotr Korektor",
      author_organization_name: "Korekcja Testowa",
      author_is_external: true,
      private: false,
      photos: ["019c5f87-fce8-739b-b960-b7a195bfc2f0"],
      summary: "Korekcja: DD M2 na LH, kontrola za 14 dni.",
      details: {},
      published_at: "2026-09-18T10:00:00Z",
    },
  ]);
  api.getFarmHealthPhoto.mockResolvedValue(new Blob(["webp"]));
  api.createFarmAnimalHealth.mockResolvedValue({
    id: "h2",
    animal_id: "a3",
    kind: "note",
    occurred_on: "2026-09-20",
    source: "farms.manual",
    source_reference: "r2",
    author_name: "Anna Rolnik",
    author_organization_name: "Gospodarstwo",
    author_is_external: false,
    private: false,
    photos: [],
    summary: "Kuleje na prawą tylną.",
    details: {},
    published_at: "2026-09-20T10:00:00Z",
  });
  sections.length = 0;
  api.listFarmAnimals.mockResolvedValue(HERD);
  api.listFarms.mockResolvedValue([
    farm("farm-1", "Nowakowie"),
    farm("farm-2", "Zagroda Lisów"),
  ]);
  api.createFarmAnimal.mockResolvedValue(HERD[0]);
  api.updateFarmAnimal.mockResolvedValue(HERD[0]);
});

function renderPanel(
  permissions: readonly string[] | null = FULL,
  locale: "pl" | "en" = "pl",
) {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      <AnimalsPanel access={access(permissions)} />
    </NextIntlClientProvider>,
  );
}

const checkAxe = async (root: Element = document.body) => {
  const results = await axe.run(root, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
};

test("pokazuje zwierzęta wszystkich gospodarstw kolumnami rejestru", async () => {
  const { container } = renderPanel();

  const table = await screen.findByRole("table", {
    name: "Zwierzęta ze wszystkich gospodarstw",
  });
  expect(
    within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent),
  ).toEqual([
    "Kolczyk",
    "Imię / nr roboczy",
    "Gospodarstwo",
    "Status",
    "Działania",
  ]);

  const rows = within(table).getAllByRole("row");
  expect(rows).toHaveLength(4);
  expect(within(rows[1]).getByText("PL005432198765")).toBeInTheDocument();
  expect(within(rows[1]).getByText(/Mućka/)).toBeInTheDocument();
  expect(within(rows[1]).getByText(/#412/)).toBeInTheDocument();
  expect(within(rows[1]).getByText("Nowakowie")).toBeInTheDocument();
  expect(within(rows[1]).getByText("W stadzie")).toBeInTheDocument();
  // Without a name the working number stands alone; without either, a dash.
  expect(within(rows[2]).getByText("#77")).toBeInTheDocument();
  expect(within(rows[3]).getByText("—")).toBeInTheDocument();
  expect(within(rows[3]).getByText("Sprzedane")).toBeInTheDocument();

  expect(screen.getByText("Znaleziono 3 zwierzęta")).toBeInTheDocument();
  await checkAxe(container);
});

test("szuka po końcówce kolczyka, zawęża do gospodarstwa i do statusu", async () => {
  renderPanel();
  await screen.findByRole("table");
  expect(api.listFarmAnimals).toHaveBeenCalledWith({
    farmId: undefined,
    search: undefined,
  });

  // The server searches, so the last digits of a tag go to it as they are.
  fireEvent.change(screen.getByLabelText("Szukaj zwierzęcia"), {
    target: { value: "98765" },
  });
  await waitFor(() =>
    expect(api.listFarmAnimals).toHaveBeenLastCalledWith({
      farmId: undefined,
      search: "98765",
    }),
  );

  fireEvent.change(screen.getByLabelText("Gospodarstwo"), {
    target: { value: "farm-2" },
  });
  await waitFor(() =>
    expect(api.listFarmAnimals).toHaveBeenLastCalledWith({
      farmId: "farm-2",
      search: "98765",
    }),
  );

  // The status filter is the one the API has no parameter for: it trims the
  // page that came back, without asking again.
  const calls = api.listFarmAnimals.mock.calls.length;
  fireEvent.change(screen.getByLabelText("Status"), {
    target: { value: "sold" },
  });
  await waitFor(() =>
    expect(screen.getByText("Znaleziono 1 zwierzę")).toBeInTheDocument(),
  );
  expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2);
  expect(api.listFarmAnimals).toHaveBeenCalledTimes(calls);
});

test("karta zwierzęcia pokazuje dane rejestru i zmienia status", async () => {
  renderPanel();

  const trigger = await screen.findByRole("button", {
    name: "PL005432100002",
  });
  fireEvent.click(trigger);
  const dialog = await screen.findByRole("dialog", { name: "PL005432100002" });
  expect(
    within(dialog).getByRole("link", { name: "Zagroda Lisów" }),
  ).toHaveAttribute("href", "/panel/farms/farm-2");
  expect(within(dialog).getByText("1 kwi 2022")).toBeInTheDocument();
  expect(within(dialog).getByText("Sprzedana na targu.")).toBeInTheDocument();
  await checkAxe();

  // Kartoteka zwierzęcia: rodzaj, treść, autor i firma, z której przyszedł.
  expect(
    await within(dialog).findByText(
      "Korekcja: DD M2 na LH, kontrola za 14 dni.",
    ),
  ).toBeVisible();
  expect(within(dialog).getByText(/Piotr Korektor/)).toBeVisible();
  expect(within(dialog).getByText(/Korekcja Testowa/)).toBeVisible();

  // Zdjęcie czytane jest przez wpis, nie przez magazyn rolnika: plik zostaje
  // u autora (decyzja z 20.09).
  await waitFor(() =>
    expect(api.getFarmHealthPhoto).toHaveBeenCalledWith(
      "h1",
      "019c5f87-fce8-739b-b960-b7a195bfc2f0",
      expect.anything(),
    ),
  );
  expect(
    await within(dialog).findByRole("img", { name: "Zdjęcie z wpisu" }),
  ).toBeVisible();

  // Filtr rodzaju pyta serwer, bo lista jest ucinana po stronie API.
  fireEvent.click(within(dialog).getByRole("button", { name: "Notatka" }));
  await waitFor(() =>
    expect(api.listFarmAnimalHealth).toHaveBeenLastCalledWith(
      "a3",
      expect.objectContaining({ kinds: ["note"] }),
    ),
  );

  // Wpis rolnika: rodzaj, treść i prywatność idą do API.
  fireEvent.click(within(dialog).getByRole("button", { name: "Dodaj wpis" }));
  fireEvent.change(within(dialog).getByLabelText("Treść wpisu"), {
    target: { value: "Kuleje na prawą tylną." },
  });
  fireEvent.click(
    within(dialog).getByLabelText(/Tylko dla mnie/, { selector: "input" }),
  );
  fireEvent.click(within(dialog).getByRole("button", { name: "Zapisz" }));
  await waitFor(() =>
    expect(api.createFarmAnimalHealth).toHaveBeenCalledWith("a3", {
      kind: "note",
      summary: "Kuleje na prawą tylną.",
      private: true,
    }),
  );

  const status = within(dialog).getByLabelText("Status") as HTMLSelectElement;
  expect(status.value).toBe("sold");
  fireEvent.change(status, { target: { value: "active" } });
  await waitFor(() =>
    expect(api.updateFarmAnimal).toHaveBeenCalledWith("a3", {
      status: "active",
    }),
  );

  fireEvent.click(within(dialog).getByRole("button", { name: "Zamknij" }));
  await waitFor(() => expect(trigger).toHaveFocus());
});

test("karta pokazuje sekcję produktu tylko temu, kto ma jej uprawnienie", async () => {
  const Section = ({
    animalId,
    farmId,
  }: {
    animalId: string;
    farmId: string;
  }) => <p>{`korekcje ${animalId} w ${farmId}`}</p>;
  sections.push(
    { id: "trimmings", component: Section, permission: "hoofcare.herd.read" },
    {
      id: "checkup",
      component: () => <p>najbliższa kontrola</p>,
      module: "vertical.hoofcare",
    },
  );

  renderPanel();
  fireEvent.click(
    await screen.findByRole("button", { name: "PL005432198765" }),
  );
  const dialog = await screen.findByRole("dialog", { name: "PL005432198765" });
  // Neither gate is met: the register's own card, nothing of the product's.
  expect(within(dialog).queryByText(/korekcje/)).toBeNull();
  expect(within(dialog).queryByText("najbliższa kontrola")).toBeNull();

  cleanup();

  // With the permission the first section renders; the second still needs a
  // module this deployment does not compose.
  renderPanel([...FULL, "hoofcare.herd.read"]);
  fireEvent.click(
    await screen.findByRole("button", { name: "PL005432198765" }),
  );
  expect(await screen.findByText("korekcje a1 w farm-1")).toBeInTheDocument();
  expect(screen.queryByText("najbliższa kontrola")).toBeNull();
});

test("dodaje zwierzę do wybranego gospodarstwa i pokazuje błąd serwera", async () => {
  renderPanel();
  await screen.findByRole("table");

  fireEvent.click(screen.getByRole("button", { name: "Dodaj zwierzę" }));
  const dialog = await screen.findByRole("dialog", { name: "Dodaj zwierzę" });
  const submit = within(dialog).getByRole("button", { name: "Dodaj zwierzę" });

  // Nothing filled in: the two required fields say so, nothing is sent.
  fireEvent.click(submit);
  expect(
    await within(dialog).findByText("Wybierz gospodarstwo."),
  ).toBeInTheDocument();
  expect(
    within(dialog).getByText("Podaj numer z kolczyka."),
  ).toBeInTheDocument();
  expect(api.createFarmAnimal).not.toHaveBeenCalled();
  await checkAxe();

  fireEvent.change(within(dialog).getByLabelText("Gospodarstwo"), {
    target: { value: "farm-2" },
  });
  fireEvent.change(within(dialog).getByLabelText("Kolczyk"), {
    target: { value: "PL 005432100003" },
  });
  api.createFarmAnimal.mockRejectedValueOnce(
    new ApiProblemError({
      type: "about:blank",
      title: "Bad Request",
      status: 400,
      code: "validation_error",
      detail: { national_id: ["To zwierzę jest już w tym gospodarstwie."] },
      correlation_id: null,
    }),
  );
  fireEvent.click(submit);
  expect(
    await within(dialog).findByText("To zwierzę jest już w tym gospodarstwie."),
  ).toBeInTheDocument();

  fireEvent.click(submit);
  await waitFor(() =>
    expect(api.createFarmAnimal).toHaveBeenLastCalledWith({
      farm_id: "farm-2",
      national_id: "PL 005432100003",
      name: "",
      working_number: "",
      sex: "female",
      birth_date: null,
    }),
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() => expect(api.listFarmAnimals).toHaveBeenCalledTimes(2));
});

test("nieudane wczytanie można ponowić, pusty rejestr prosi o pierwszą sztukę", async () => {
  api.listFarmAnimals.mockRejectedValueOnce(new Error("offline"));
  const { container } = renderPanel();

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent("Nie udało się wczytać zwierząt.");
  expect(screen.queryByRole("table")).toBeNull();

  api.listFarmAnimals.mockResolvedValueOnce([]);
  fireEvent.click(
    within(alert).getByRole("button", { name: "Spróbuj ponownie" }),
  );
  expect(
    await screen.findByText(
      "Nie ma jeszcze żadnego zwierzęcia. Dodaj pierwsze.",
    ),
  ).toBeInTheDocument();
  // The empty state repeats the one next step, next to the empty list.
  expect(screen.getAllByRole("button", { name: "Dodaj zwierzę" })).toHaveLength(
    2,
  );
  await checkAxe(container);
});

test("lists the register in English and never fakes trimming columns", async () => {
  const { container } = renderPanel(FULL, "en");

  const table = await screen.findByRole("table", {
    name: "Animals of all farms",
  });
  expect(
    within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent),
  ).toEqual(["Ear tag", "Name / working no.", "Farm", "Status", "Actions"]);
  expect(screen.getByText("Found 3 animals")).toBeInTheDocument();
  expect(screen.getByLabelText("Farm")).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Add animal" }),
  ).toBeInTheDocument();
  await checkAxe(container);
});

test("bez uprawnienia farms.read mówi o braku dostępu i nic nie pobiera", () => {
  renderPanel(["booking.appointment.read"]);

  expect(screen.getByText("Brak dostępu do rejestru")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Dodaj zwierzę" })).toBeNull();
  expect(api.listFarmAnimals).not.toHaveBeenCalled();
  expect(api.listFarms).not.toHaveBeenCalled();
});

test("bez organizacji prosi o jej wybór", () => {
  renderPanel(null);

  expect(screen.getByText("Wybierz organizację")).toBeInTheDocument();
  expect(api.listFarmAnimals).not.toHaveBeenCalled();
});

test("sztuki wpisane przez firmę czekają na przejrzenie", async () => {
  api.listFarmAnimals.mockResolvedValue([
    {
      ...HERD[0],
      review_requested_at: "2026-09-20T08:00:00Z",
    },
  ]);
  renderPanel();

  // Licznik mówi, ile sztuk czeka; znacznik stoi przy samym zwierzęciu.
  expect(
    await screen.findByRole("button", { name: "Do przejrzenia (1)" }),
  ).toBeVisible();
  expect(screen.getByText("Nowe od firmy")).toBeVisible();

  // Filtr pyta serwer, a nie chowa wierszy w panelu.
  fireEvent.click(screen.getByRole("button", { name: "Do przejrzenia (1)" }));
  await waitFor(() =>
    expect(api.listFarmAnimals).toHaveBeenLastCalledWith(
      expect.objectContaining({ review: true }),
    ),
  );

  // Hodowca potwierdza w karcie zwierzęcia; nic nie znika z rejestru.
  fireEvent.click(
    await screen.findByRole("button", { name: HERD[0].national_id }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: HERD[0].national_id,
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Przejrzane" }));
  await waitFor(() =>
    expect(api.updateFarmAnimal).toHaveBeenCalledWith(HERD[0].id, {
      reviewed: true,
    }),
  );
});

test("edycja zwierzęcia jest zawsze w wierszu i wysyła tylko zmiany", async () => {
  api.updateFarmAnimal.mockResolvedValue({ ...HERD[0], name: "Krasula" });
  renderPanel();
  const row = (await screen.findByText("PL005432198765")).closest("tr")!;
  // Edycja nie chowa się pod „…” (ADR-057).
  const edit = within(row).getByRole("button", { name: "Edytuj zwierzę" });
  fireEvent.click(edit);
  const dialog = await screen.findByRole("dialog", { name: "Edytuj zwierzę" });
  fireEvent.change(within(dialog).getByLabelText("Imię"), {
    target: { value: "Krasula" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Zapisz zmiany" }),
  );
  await waitFor(() =>
    expect(api.updateFarmAnimal).toHaveBeenCalledWith("a1", {
      name: "Krasula",
    }),
  );
  expect(await screen.findByText("Zapisano: PL005432198765.")).toBeVisible();
});

test("bez farms.manage wiersz nie proponuje edycji", async () => {
  renderPanel(["farms.read"]);
  const row = (await screen.findByText("PL005432198765")).closest("tr")!;
  expect(
    within(row).queryByRole("button", { name: "Edytuj zwierzę" }),
  ).toBeNull();
});

test("zwierzę w karencji ma czerwoną odznakę z końcem karencji mleka i mięsa", async () => {
  api.listFarmAnimals.mockResolvedValue([
    animal("a1", "PL005432198765", {
      withdrawal_milk_until: "2026-09-28T16:00:00Z",
      withdrawal_meat_until: "2026-10-22T08:00:00Z",
    }),
    ...HERD.slice(1),
  ]);
  renderPanel();
  const table = await screen.findByRole("table", {
    name: "Zwierzęta ze wszystkich gospodarstw",
  });
  const [, first, second] = within(table).getAllByRole("row");
  expect(
    within(first).getByText(
      "Karencja: mleko do 28 wrz, 18:00 · mięso do 22 paź, 10:00",
    ),
  ).toBeInTheDocument();
  expect(within(second).queryByText(/Karencja/)).toBeNull();
});
