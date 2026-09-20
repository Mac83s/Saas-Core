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
  expect(
    screen.getByRole("link", { name: "Wszystkie gospodarstwa" }),
  ).toHaveAttribute("href", "/panel/farms");
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
