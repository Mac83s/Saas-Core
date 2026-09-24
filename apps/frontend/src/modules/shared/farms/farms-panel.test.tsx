import type { ReactNode } from "react";
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

import { ApiProblemError, type Farm } from "@saas-core/api-client";

import englishMessages from "../../../../messages/en.json";
import polishMessages from "../../../../messages/pl.json";
import { FarmDetail } from "./farm-detail";
import { FarmsPanel } from "./farms-panel";

const api = vi.hoisted(() => ({
  createFarm: vi.fn(),
  createFarmAnimal: vi.fn(),
  issueFarmActivationCode: vi.fn(),
  listFarmShares: vi.fn(),
  redeemFarmActivationCode: vi.fn(),
  revokeFarmShare: vi.fn(),
  sendFarmHerd: vi.fn(),
  listFarmAnimals: vi.fn(),
  listFarmSpecies: vi.fn(),
  listFarmVisits: vi.fn(),
  setFarmShareSchedule: vi.fn(),
  listFarms: vi.fn(),
  readFarm: vi.fn(),
  updateFarm: vi.fn(),
  updateFarmAnimal: vi.fn(),
}));

vi.mock("@saas-core/api-client", async (original) => ({
  ...(await original<typeof import("@saas-core/api-client")>()),
  ...api,
}));
vi.mock("#i18n/navigation", () => ({ Link: "a" }));

const FARM = "019c5f87-fce8-739b-b960-b7a195bfc298";

function farm(overrides: Partial<Farm> = {}): Farm {
  return {
    id: FARM,
    name: "Zielona Dolina",
    herd_number: "PL012345678001",
    tax_id: "1234567890",
    village: "Wólka",
    address: "Dolna 4",
    keeper_name: "Anna Nowak",
    email: "anna@example.com",
    phone: "600 700 800",
    housing: "",
    notes: "Wjazd od strony lasu.",
    active: true,
    animal_count: 2,
    updated_at: "2026-09-18T09:00:00Z",
    ...overrides,
  };
}

function share(overrides: Record<string, unknown> = {}) {
  return {
    id: "019c5f87-fce8-739b-b960-b7a195bfc2aa",
    registry_farm_id: FARM,
    company_farm_id: "019c5f87-fce8-739b-b960-b7a195bfc2ab",
    company_organization_id: "019c5f87-fce8-739b-b960-b7a195bfc2ac",
    registry_organization_id: "019c5f87-fce8-739b-b960-b7a195bfc2ad",
    can_write_herd: true,
    can_publish_schedule: false,
    can_publish_health: true,
    basis: "activation_code",
    status: "active",
    granted_at: "2026-09-18T09:00:00Z",
    revoked_at: null,
    partner_name: "Korekcja Kowalski",
    partner_is_company: true,
    ...overrides,
  };
}

const animals = [
  {
    id: "animal-1",
    farm_id: FARM,
    farm_name: "Zielona Dolina",
    species: "cattle",
    national_id: "PL005432198765",
    working_number: "12",
    name: "Mućka",
    sex: "female",
    birth_date: "2022-03-04",
    status: "active",
    notes: "",
    updated_at: "2026-09-15T07:30:00Z",
  },
  {
    id: "animal-2",
    farm_id: FARM,
    farm_name: "Zielona Dolina",
    species: "cattle",
    national_id: "PL005432100001",
    working_number: "",
    name: "",
    sex: "female",
    birth_date: null,
    status: "sold",
    notes: "",
    updated_at: "2026-09-16T07:30:00Z",
  },
];

// Termin liczony od „teraz": inaczej ten sam test byłby przyszły dziś i
// przeszły za miesiąc.
const SOON = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();

function visits(overrides: Record<string, unknown>[] = []) {
  return [
    {
      id: "visit-planned",
      status: "planned",
      scheduled_for: SOON,
      occurred_on: null,
      company_name: "Korekcja Kowalski",
      summary: "Korekcja, piątek rano.",
      details: {},
    },
    {
      id: "visit-done",
      status: "done",
      scheduled_for: "2026-09-15T06:00:00Z",
      occurred_on: "2026-09-15",
      company_name: "Korekcja Kowalski",
      summary: "Skorygowano 12 sztuk.",
      details: {
        sections: [
          {
            title: "Racice",
            rows: [
              { label: "Sztuk", value: "12" },
              { label: "Kulawizny", value: "2" },
            ],
          },
        ],
      },
    },
    {
      id: "visit-canceled",
      status: "canceled",
      scheduled_for: null,
      occurred_on: null,
      company_name: "Korekcja Kowalski",
      summary: "Odwołana, choroba.",
      details: {},
    },
    ...overrides,
  ];
}

const problem = (status: number, code: string) =>
  new ApiProblemError({
    type: "about:blank",
    title: "Problem",
    status,
    code,
    detail: "Nie.",
    correlation_id: null,
  });

beforeEach(() => {
  vi.clearAllMocks();
  api.listFarms.mockResolvedValue([
    farm(),
    farm({
      id: "019c5f87-fce8-739b-b960-b7a195bfc299",
      name: "Pod Lipami",
      herd_number: "",
      village: "",
      keeper_name: "",
      phone: "",
      animal_count: 0,
    }),
  ]);
  api.readFarm.mockResolvedValue(farm());
  api.listFarmAnimals.mockResolvedValue(animals);
  api.listFarmSpecies.mockResolvedValue([
    { key: "cattle", label: { pl: "Bydło", en: "Cattle" }, active: true },
    { key: "sheep", label: { pl: "Owce", en: "Sheep" }, active: false },
  ]);
  api.createFarm.mockResolvedValue(farm({ name: "Nowe Pole" }));
  api.createFarmAnimal.mockResolvedValue(animals[0]);
  api.updateFarm.mockResolvedValue(farm({ notes: "Nowa notatka." }));
  api.updateFarmAnimal.mockResolvedValue({ ...animals[0], status: "sold" });
  api.listFarmShares.mockResolvedValue([]);
  api.issueFarmActivationCode.mockResolvedValue({
    code: "ABCD-EFGH-JKLM-NPQR",
    expires_at: "2026-10-20T09:00:00Z",
  });
  api.redeemFarmActivationCode.mockResolvedValue({
    farm: farm({ name: "Zielona Dolina" }),
    created: true,
    animals_added: 2,
    share: share(),
  });
  api.sendFarmHerd.mockResolvedValue({ added: 2, updated: 1, unchanged: 7 });
  api.revokeFarmShare.mockImplementation(async () =>
    share({ status: "revoked", revoked_at: "2026-09-20T09:00:00Z" }),
  );
  api.listFarmVisits.mockResolvedValue(visits());
  api.setFarmShareSchedule.mockImplementation(async (_id, allowed) =>
    share({ can_publish_schedule: allowed }),
  );
});

function wrap(children: ReactNode, locale: "pl" | "en" = "pl") {
  return render(
    <NextIntlClientProvider
      locale={locale}
      messages={locale === "pl" ? polishMessages : englishMessages}
      timeZone="Europe/Warsaw"
    >
      {children}
    </NextIntlClientProvider>,
  );
}

async function expectAccessible(container: HTMLElement) {
  const results = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results.violations).toEqual([]);
}

test("lista pokazuje tylko to, co rejestr wie o gospodarstwie", async () => {
  const { container } = wrap(<FarmsPanel canManage canRead />);

  const table = await screen.findByRole("table", {
    name: /Gospodarstwa: nazwa, miejscowość/,
  });
  const rows = within(table).getAllByRole("row");
  expect(rows).toHaveLength(3);
  const first = within(rows[1]);
  expect(first.getByRole("link", { name: "Zielona Dolina" })).toHaveAttribute(
    "href",
    `/panel/farms/${FARM}`,
  );
  expect(first.getByText("PL012345678001")).toBeInTheDocument();
  expect(first.getAllByText("Wólka").length).toBeGreaterThan(0);
  expect(first.getByText("Anna Nowak")).toBeInTheDocument();
  expect(first.getByRole("link", { name: "600 700 800" })).toHaveAttribute(
    "href",
    "tel:600700800",
  );
  expect(first.getByText("2")).toBeInTheDocument();
  // A farm with no keeper and no phone shows a dash, never an invented one.
  expect(within(rows[2]).getAllByText("—")).not.toHaveLength(0);

  await expectAccessible(container);
});

test("wyszukiwarka pyta serwer i da się ją wyczyścić", async () => {
  wrap(<FarmsPanel canManage canRead />);
  await screen.findByRole("table");

  api.listFarms.mockResolvedValueOnce([]);
  fireEvent.change(screen.getByLabelText(/Szukaj: nazwa/), {
    target: { value: "wólka" },
  });
  await waitFor(() => expect(api.listFarms).toHaveBeenCalledWith("wólka"));
  expect(await screen.findByText("Nic nie pasuje do wyszukiwania."));

  fireEvent.click(screen.getByRole("button", { name: "Wyczyść wyszukiwanie" }));
  await waitFor(() =>
    expect(api.listFarms).toHaveBeenLastCalledWith(undefined),
  );
});

test("pusty rejestr tłumaczy następny krok i dodaje gospodarstwo", async () => {
  api.listFarms.mockResolvedValue([]);
  const { container } = wrap(<FarmsPanel canManage canRead />);

  expect(
    await screen.findByText("Nie ma tu jeszcze żadnego gospodarstwa"),
  ).toBeInTheDocument();
  await expectAccessible(container);

  fireEvent.click(
    screen.getAllByRole("button", { name: "Dodaj gospodarstwo" })[1],
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Dodaj gospodarstwo",
  });
  fireEvent.change(within(dialog).getByLabelText("Nazwa gospodarstwa"), {
    target: { value: "Nowe Pole" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Dodaj gospodarstwo" }),
  );
  await waitFor(() =>
    expect(api.createFarm).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Nowe Pole" }),
    ),
  );
  expect(
    await screen.findByText("Dodano gospodarstwo: Nowe Pole."),
  ).toBeInTheDocument();
});

test("bez farms.read nic nie pobiera i mówi o braku dostępu", () => {
  wrap(<FarmsPanel />);

  expect(screen.getByText("Brak dostępu do gospodarstw")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Dodaj gospodarstwo" }),
  ).toBeNull();
  expect(api.listFarms).not.toHaveBeenCalled();
});

test("błąd wczytania da się ponowić, brak w planie prowadzi do abonamentu", async () => {
  api.listFarms.mockRejectedValueOnce(new Error("sieć"));
  wrap(<FarmsPanel canRead />);

  expect(
    await screen.findByText("Nie udało się wczytać gospodarstw."),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  await screen.findByRole("table");

  api.listFarms.mockRejectedValue(problem(403, "entitlement_required"));
  fireEvent.change(screen.getByLabelText(/Szukaj: nazwa/), {
    target: { value: "x" },
  });
  expect(
    await screen.findByText(
      "Rejestr gospodarstw nie jest dostępny w planie tej organizacji.",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: "Zobacz abonament" }),
  ).toHaveAttribute("href", "/panel/settings/billing");
});

test("karta gospodarstwa: kontakt, mapa, stado i notatka (EN)", async () => {
  const { container } = wrap(
    <FarmDetail canManage canRead farmId={FARM} />,
    "en",
  );

  expect(
    await screen.findByRole("heading", { level: 1, name: "Zielona Dolina" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("link", { name: /Dolna 4, Wólka.*opens a map/ }),
  ).toHaveAttribute(
    "href",
    "https://www.google.com/maps/search/?api=1&query=Zielona%20Dolina%2C%20Dolna%204%2C%20W%C3%B3lka",
  );
  expect(screen.getByRole("link", { name: "600 700 800" })).toHaveAttribute(
    "href",
    "tel:600700800",
  );
  expect(
    screen.getByRole("link", { name: "anna@example.com" }),
  ).toHaveAttribute("href", "mailto:anna@example.com");
  expect(screen.getByText("2 animals")).toBeInTheDocument();
  expect(screen.getByText("Herd number: PL012345678001")).toBeInTheDocument();

  const table = await screen.findByRole("table", { name: /^Animals:/ });
  const rows = within(table).getAllByRole("row");
  expect(within(rows[1]).getByText("PL005432198765")).toBeInTheDocument();
  expect(within(rows[1]).getByText("Mućka · #12 · Cattle")).toBeInTheDocument();
  // "Last change" is the animal's updated_at — the only date the API has.
  expect(within(rows[1]).getByText(/2026/)).toBeInTheDocument();
  await expectAccessible(container);

  fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
  expect(await screen.findByText("Wjazd od strony lasu.")).toBeInTheDocument();
});

test("zmiana statusu i dodanie zwierzęcia mówią, co się stało", async () => {
  wrap(<FarmDetail canManage canRead farmId={FARM} />);
  await screen.findByRole("table", { name: /^Zwierzęta:/ });

  fireEvent.change(screen.getByLabelText("Status: PL005432198765"), {
    target: { value: "sold" },
  });
  await waitFor(() =>
    expect(api.updateFarmAnimal).toHaveBeenCalledWith("animal-1", {
      status: "sold",
    }),
  );
  expect(
    await screen.findByText("Zapisano status: PL005432198765."),
  ).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Dodaj zwierzę" }));
  const dialog = await screen.findByRole("dialog", { name: "Dodaj zwierzę" });
  // Only an active species may be recorded; the rest say "soon".
  const species = within(dialog).getByLabelText("Gatunek");
  expect(
    within(species)
      .getAllByRole("option")
      .map((option) => [
        option.textContent,
        (option as HTMLOptionElement).disabled,
      ]),
  ).toEqual([
    ["Bydło", false],
    ["Owce (wkrótce)", true],
  ]);
  fireEvent.change(within(dialog).getByLabelText("Numer identyfikacyjny"), {
    target: { value: "PL 005432100002" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Dodaj zwierzę" }),
  );
  await waitFor(() =>
    expect(api.createFarmAnimal).toHaveBeenCalledWith(
      expect.objectContaining({
        farm_id: FARM,
        national_id: "PL 005432100002",
        species: "cattle",
      }),
    ),
  );
  expect(
    await screen.findByText("Dodano zwierzę: PL005432198765."),
  ).toBeInTheDocument();
});

test("bez farms.manage karta jest do czytania, a błąd 404 to osobny stan", async () => {
  wrap(<FarmDetail canRead farmId={FARM} />);

  await screen.findByRole("table", { name: /^Zwierzęta:/ });
  expect(
    screen.queryByRole("button", { name: "Edytuj gospodarstwo" }),
  ).toBeNull();
  expect(screen.queryByRole("button", { name: "Dodaj zwierzę" })).toBeNull();
  expect(screen.queryByLabelText("Status: PL005432198765")).toBeNull();
  expect(screen.getByText("W stadzie")).toBeInTheDocument();
});

test("gospodarstwo spoza organizacji nie kusi ponowieniem", async () => {
  api.readFarm.mockRejectedValue(problem(404, "not_found"));
  wrap(<FarmDetail canManage canRead farmId={FARM} />);

  expect(
    await screen.findByText(
      "Nie ma takiego gospodarstwa albo nie masz do niego dostępu.",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Spróbuj ponownie" })).toBeNull();
  // The way back up is the page's eyebrow, as on every nested page.
  expect(screen.getByRole("link", { name: "Gospodarstwa" })).toHaveAttribute(
    "href",
    "/panel/farms",
  );
});

test("kod aktywacji dla karty firmy, a hodowca cofa dostęp", async () => {
  wrap(<FarmDetail canManage canRead farmId={FARM} />);
  fireEvent.click(await screen.findByRole("tab", { name: "Dostęp" }));

  // Nikt jeszcze nie jest połączony: firma generuje kod dla hodowcy.
  expect(await screen.findByText(/nie jest z nikim połączone/)).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "Wygeneruj kod aktywacji" }),
  );
  expect(await screen.findByText("ABCD-EFGH-JKLM-NPQR")).toBeVisible();

  // Po przejęciu to hodowca decyduje, kiedy dostęp się kończy.
  api.listFarmShares.mockResolvedValue([share()]);
  cleanup();
  wrap(<FarmDetail canManage canRead farmId={FARM} />);
  fireEvent.click(await screen.findByRole("tab", { name: "Dostęp" }));
  expect(await screen.findByText("Korekcja Kowalski")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Wygeneruj kod aktywacji" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Cofnij dostęp" }));
  await waitFor(() =>
    expect(api.revokeFarmShare).toHaveBeenCalledWith(share().id),
  );
  expect(await screen.findByText("Cofnięte")).toBeVisible();
});

test("hodowca przejmuje gospodarstwo kodem, zły kod tłumaczy się na miejscu", async () => {
  api.redeemFarmActivationCode.mockRejectedValueOnce(
    problem(400, "validation_error"),
  );
  wrap(<FarmsPanel canManage canRead />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Przejmij gospodarstwo kodem" }),
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Przejmij gospodarstwo kodem",
  });
  fireEvent.change(within(dialog).getByLabelText("Kod aktywacji"), {
    target: { value: "abcdefghjklmnpqr" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Przejmij" }));
  expect(await within(dialog).findByRole("alert")).toBeVisible();

  fireEvent.click(within(dialog).getByRole("button", { name: "Przejmij" }));
  await waitFor(() =>
    expect(api.redeemFarmActivationCode).toHaveBeenLastCalledWith(
      "abcdefghjklmnpqr",
    ),
  );
  expect(
    await screen.findByText(
      "Przejęto gospodarstwo Zielona Dolina. Dopisane zwierzęta: 2.",
    ),
  ).toBeInTheDocument();
});

test("firma dosyła stado do rejestru, a kod znika po połączeniu", async () => {
  // Karta firmy: udział istnieje, więc partnerem jest hodowca, nie firma.
  api.listFarmShares.mockResolvedValue([
    share({ partner_name: "Gospodarstwo Nowak", partner_is_company: false }),
  ]);
  wrap(<FarmDetail canManage canRead farmId={FARM} />);
  fireEvent.click(await screen.findByRole("tab", { name: "Dostęp" }));

  // Kod przekazania zamraża kartę w chwili wydania, więc sztuki dopisane
  // później dosyła osobna akcja.
  fireEvent.click(
    await screen.findByRole("button", { name: "Wyślij stado do rejestru" }),
  );
  await waitFor(() => expect(api.sendFarmHerd).toHaveBeenCalledWith(FARM));
  expect(
    await screen.findByText(
      "Wysłano do rejestru: dopisano 2, poprawiono 1, bez zmian 7.",
    ),
  ).toBeInTheDocument();

  // Połączonej karcie nie wydaje się drugiego kodu — API i tak odpowiada 409.
  expect(
    screen.queryByRole("button", { name: "Wygeneruj kod aktywacji" }),
  ).toBeNull();
});

test("kartoteka wizyt: przyszłe oddzielone od przeszłych, raport się rozwija", async () => {
  // Rejestr rolnika: gospodarstwo jest udostępnione firmie, więc wizyty mają
  // skąd przyjść. Na karcie firmy tej zakładki nie ma w ogóle.
  api.listFarmShares.mockResolvedValue([share()]);
  const { container } = wrap(<FarmDetail canManage canRead farmId={FARM} />);

  fireEvent.click(await screen.findByRole("tab", { name: "Wizyty" }));
  await waitFor(() => expect(api.listFarmVisits).toHaveBeenCalledWith(FARM));

  const upcoming = (
    await screen.findByRole("heading", { name: "Przyszłe wizyty" })
  ).parentElement as HTMLElement;
  expect(within(upcoming).getByText("Zaplanowana")).toBeVisible();
  expect(within(upcoming).getByText("Korekcja, piątek rano.")).toBeVisible();
  // Odbyta wizyta nigdy nie trafia do przyszłych, choć ma też termin.
  expect(within(upcoming).queryByText("Odbyta")).toBeNull();

  const past = screen.getByRole("heading", { name: "Przeszłe wizyty" })
    .parentElement as HTMLElement;
  expect(within(past).getByText("Odbyta")).toBeVisible();
  expect(within(past).getByText("Odwołana")).toBeVisible();
  expect(within(past).getByText("Skorygowano 12 sztuk.")).toBeVisible();
  // Wizyta bez żadnej daty mówi to wprost, zamiast udawać dzisiejszą.
  expect(within(past).getByText("nie podano")).toBeVisible();

  // Raport rozwija tylko wiersz odbyty i tylko z treścią: zaplanowana i
  // odwołana nie mają czego pokazać.
  const toggles = screen.getAllByText("Raport");
  expect(toggles).toHaveLength(1);
  expect(screen.getByText("Kulawizny")).not.toBeVisible();
  fireEvent.click(toggles[0]);
  expect(screen.getByText("Kulawizny")).toBeVisible();
  expect(screen.getByText("Racice")).toBeVisible();
  expect(screen.getByText("12")).toBeVisible();

  await expectAccessible(container);
});

test("wizyty po angielsku, a nieznany kształt raportu nie wysypuje ekranu", async () => {
  api.listFarmShares.mockResolvedValue([share()]);
  api.listFarmVisits.mockResolvedValue([
    {
      id: "visit-strange",
      status: "done",
      scheduled_for: null,
      occurred_on: "2026-09-15",
      company_name: "Korekcja Kowalski",
      summary: "Skorygowano 12 sztuk.",
      // Wertykał, którego rdzeń nie zna, przysłał coś swojego (ADR-052 pkt 7).
      details: { icar: [{ code: "HOOF-03" }] },
    },
  ]);
  const { container } = wrap(
    <FarmDetail canManage canRead farmId={FARM} />,
    "en",
  );

  fireEvent.click(await screen.findByRole("tab", { name: "Visits" }));
  expect(
    await screen.findByRole("heading", { name: "Upcoming visits" }),
  ).toBeVisible();
  expect(screen.getByText("Nothing is booked yet.")).toBeVisible();
  expect(screen.getByText("Done")).toBeVisible();

  fireEvent.click(screen.getByText("Report"));
  expect(
    screen.getByText(
      "The company sent a report in a form we cannot show here. Ask them for the details.",
    ),
  ).toBeVisible();
  await expectAccessible(container);
});

test("pusta kartoteka wizyt tłumaczy, czego brakuje, a błąd da się ponowić", async () => {
  api.listFarmShares.mockResolvedValue([share()]);
  api.listFarmVisits.mockRejectedValueOnce(new Error("sieć"));
  wrap(<FarmDetail canManage canRead farmId={FARM} />);

  fireEvent.click(await screen.findByRole("tab", { name: "Wizyty" }));
  expect(
    await screen.findByText("Nie udało się wczytać gospodarstw."),
  ).toBeInTheDocument();

  api.listFarmVisits.mockResolvedValue([]);
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  expect(await screen.findByText(/Żadna firma nie przysłała/)).toBeVisible();
});

test("karta firmy nie ma zakładki wizyt ani zgody na grafik", async () => {
  api.listFarmShares.mockResolvedValue([
    share({ partner_name: "Gospodarstwo Nowak", partner_is_company: false }),
  ]);
  wrap(<FarmDetail canManage canRead farmId={FARM} />);

  await screen.findByRole("tab", { name: "Zwierzęta" });
  expect(screen.queryByRole("tab", { name: "Wizyty" })).toBeNull();
  expect(api.listFarmVisits).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("tab", { name: "Dostęp" }));
  expect(
    await screen.findByRole("button", { name: "Wyślij stado do rejestru" }),
  ).toBeVisible();
  expect(screen.queryByLabelText(/Zgoda na grafik/)).toBeNull();
});

test("rolnik włącza zgodę na grafik i słyszy, co się zmieniło", async () => {
  api.listFarmShares.mockResolvedValue([share()]);
  const { container } = wrap(<FarmDetail canManage canRead farmId={FARM} />);

  fireEvent.click(await screen.findByRole("tab", { name: "Dostęp" }));
  const consent = await screen.findByLabelText("Zgoda na grafik tej firmy");
  // Wyłączone to stan domyślny, więc mówi, co znaczy — nie wygląda na błąd.
  expect(consent).not.toBeChecked();
  expect(screen.getByText(/^Wyłączone — tak jest domyślnie/)).toBeVisible();
  expect(
    screen.getByText(
      "Po włączeniu Korekcja Kowalski przysyła tu terminy swoich wizyt i raporty z nich, a Ty widzisz je w zakładce Wizyty.",
    ),
  ).toBeVisible();
  await expectAccessible(container);

  fireEvent.click(consent);
  await waitFor(() =>
    expect(api.setFarmShareSchedule).toHaveBeenCalledWith(share().id, true),
  );
  expect(
    await screen.findByText("Włączono zgodę na grafik: Korekcja Kowalski."),
  ).toBeInTheDocument();
  expect(
    await screen.findByLabelText("Zgoda na grafik tej firmy"),
  ).toBeChecked();
});

test("bez farms.manage zgoda jest tylko do odczytu", async () => {
  api.listFarmShares.mockResolvedValue([share({ can_publish_schedule: true })]);
  wrap(<FarmDetail canRead farmId={FARM} />);

  fireEvent.click(await screen.findByRole("tab", { name: "Dostęp" }));
  const consent = await screen.findByLabelText("Zgoda na grafik tej firmy");
  expect(consent).toBeChecked();
  expect(consent).toBeDisabled();
  expect(screen.queryByRole("button", { name: "Cofnij dostęp" })).toBeNull();
});
