"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { ChevronRightIcon } from "lucide-react";

import {
  ApiProblemError,
  changeAssistantProfile,
  getAssistantSetup,
  type AssistantSetup,
  type AssistantSetupQuestion,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import { Input } from "@saas-core/ui/components/input";
import { Textarea } from "@saas-core/ui/components/textarea";

type Locale = "pl" | "en";
type Origin =
  "owner" | "account" | "existing_site" | "preset_default" | "assistant";
/** One value of the profile: what was said, by whom, and whether the owner
 *  confirmed it. */
type Said<T = unknown> = { value: T; origin: Origin; confirmed: boolean };
type Rule = { weekday: number; start: string; end: string; place: string };
type Price = { amount: string; currency: string; per: string };
/** A place, a person or an offer: other entries name it by its key. */
type Entry = {
  key: string;
  name?: Said<string>;
  hours?: Said<Rule[]>;
  places?: Said<string[]>;
  people?: Said<string[]>;
  inputs?: Record<string, Said>;
  [field: string]: unknown;
};
/** The `company-profile.v1` document, as far as this block reads it. */
type Profile = {
  company?: Record<string, Said>;
  card?: Record<string, Said>;
  languages?: Said<string[]>;
  places?: Entry[];
  people?: Entry[];
  offers?: Entry[];
};
type Changes = Record<string, unknown>;
/** One value as the block shows it. */
type Row = {
  /** Where it lives: `company.city`, `offers.cut.inputs.deposit`. */
  path: string[];
  label: string;
  /** The label with whose it is; what the row's buttons are named by. */
  name: string;
  text: string;
  said: Said;
  /** What „Popraw” takes: text, a longer text or a whole number. */
  edit?: "text" | "long" | "number";
};

const LISTS = ["places", "people", "offers"] as const;
type ListName = (typeof LISTS)[number];
/** The values of each part of the profile, in the order they are shown. */
const FIELDS: Record<"company" | "card" | ListName, readonly string[]> = {
  company: [
    "name",
    "activity",
    "city",
    "category",
    "address",
    "phone",
    "email",
  ],
  card: ["headline", "description"],
  places: ["name", "address"],
  people: ["name", "hours"],
  offers: [
    "name",
    "preset",
    "duration_minutes",
    "units",
    "capacity",
    "price",
    "places",
    "people",
  ],
};
const WHOLE_NUMBERS = new Set(["duration_minutes", "units", "capacity"]);
/** What a step's ref calls an entry of each list: `place:salon`. */
const KINDS = { places: "place", people: "person", offers: "offer" } as const;
/** The list a step's ref names an entry of; a week of hours is a person's. */
const REF_LISTS: Partial<Record<string, ListName>> = {
  place: "places",
  person: "people",
  offer: "offers",
  hours: "people",
};
const CONFLICT = "assistant_profile_version_conflict";

function isList(name: string | undefined): name is ListName {
  return LISTS.includes(name as ListName);
}

/** Plain text and whole numbers are corrected here; the rest in the conversation. */
function editable(path: string[]): Row["edit"] {
  const [section, key, field] = path;
  if (section === "company") return key === "category" ? undefined : "text";
  if (section === "card") return key === "description" ? "long" : "text";
  // A list's own value: not the languages, nor a kind of booking's answer.
  if (path.length !== 3) return undefined;
  if (WHOLE_NUMBERS.has(field)) return "number";
  return field === "name" || field === "address" ? "text" : undefined;
}

/**
 * The lists of a changed document, as a merge patch. A list is replaced
 * whole, and the three go together: the document shown already holds the
 * places and people of the account, which the saved profile may not — a list
 * sent alone could point at a place that is not saved yet, and be refused.
 */
function lists(profile: Profile): Changes {
  return Object.fromEntries(
    LISTS.flatMap((name) => (profile[name] ? [[name, profile[name]]] : [])),
  );
}

/** The merge patch that puts a value at `path`, or with null takes it out. */
function patch(profile: Profile, path: string[], said: Said | null): Changes {
  const [section, key, field, input] = path;
  if (!isList(section)) return { [section]: key ? { [key]: said } : said };
  const next = structuredClone(profile);
  for (const entry of next[section] ?? []) {
    if (entry.key !== key) continue;
    const holder: Record<string, unknown> = input
      ? (entry.inputs ??= {})
      : entry;
    if (said) holder[input ?? field] = said;
    else delete holder[input ?? field];
    if (entry.inputs && !Object.keys(entry.inputs).length) delete entry.inputs;
  }
  return lists(next);
}

/**
 * The merge patch that takes an entry out with everything that points at its
 * key — an offer's places and people, a person's hours at a place. A key left
 * pointing at nothing is refused by the server.
 */
function withoutEntry(profile: Profile, list: ListName, key: string): Changes {
  const next = structuredClone(profile);
  next[list] = (next[list] ?? []).filter((entry) => entry.key !== key);
  if (list !== "offers") {
    for (const offer of next.offers ?? []) {
      const links = offer[list];
      if (links) links.value = links.value.filter((item) => item !== key);
    }
  }
  if (list === "places") {
    for (const person of next.people ?? []) {
      const hours = person.hours;
      if (hours) hours.value = hours.value.filter((rule) => rule.place !== key);
    }
  }
  return lists(next);
}

/**
 * The company profile beside a setup conversation (ADR-076, A3-2): what the
 * assistant knows and from whom, what it will still ask, what is ready, what
 * waits and what the product cannot do yet. A value can be confirmed,
 * corrected or removed here. That changes the profile only — what was said,
 * not the account; a plan still waits for the click in the consent dialog.
 *
 * Nothing is shown by its key: a category, a kind of booking, an entry and a
 * field are said in words, or by a neutral text where there are none.
 */
export function SetupProfile({
  conversationId,
  revision,
}: {
  conversationId: string;
  /** Changes when the conversation settles: the profile is read again. */
  revision: number;
}) {
  const t = useTranslations("Assistant");
  const [setup, setSetup] = useState<AssistantSetup>();
  const [problem, setProblem] = useState<string>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getAssistantSetup(conversationId, controller.signal)
      .then((next) => {
        setSetup(next);
        setProblem(undefined);
      })
      .catch(() => {
        if (!controller.signal.aborted) setProblem(t("profileLoadError"));
      });
    return () => controller.abort();
  }, [conversationId, revision, t]);

  /** Saves against the version shown, then shows what the profile holds. */
  async function save(changes: Changes): Promise<boolean> {
    if (!setup || busy) return false;
    setBusy(true);
    setProblem(undefined);
    try {
      await changeAssistantProfile(changes, setup.version, crypto.randomUUID());
      setSetup(await getAssistantSetup(conversationId));
      return true;
    } catch (error) {
      const moved =
        error instanceof ApiProblemError && error.problem.code === CONFLICT;
      if (moved) {
        // The assistant, or another window, changed it first: show theirs.
        await getAssistantSetup(conversationId)
          .then(setSetup)
          .catch(() => undefined);
      }
      setProblem(t(moved ? "profileConflict" : "profileSaveError"));
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="group rounded-lg border text-sm" open>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-4 py-3 font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRightIcon
          aria-hidden="true"
          className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90"
        />
        {t("profileTitle")}
      </summary>
      <div className="space-y-5 border-t px-4 py-3">
        {problem ? (
          <p className="text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        {setup ? (
          <Overview busy={busy} onSave={save} setup={setup} />
        ) : problem ? null : (
          <p className="text-muted-foreground" role="status">
            {t("profileLoading")}
          </p>
        )}
      </div>
    </details>
  );
}

function Overview({
  setup,
  busy,
  onSave,
}: {
  setup: AssistantSetup;
  busy: boolean;
  onSave: (changes: Changes) => Promise<boolean>;
}) {
  const t = useTranslations("Assistant");
  const locale = useLocale() as Locale;
  const format = useFormatter();
  const profile = setup.document as Profile;

  // A key is the document's own name for an entry: a person never reads one.
  const entryName = (list: ListName, key: string): string =>
    profile[list]?.find((entry) => entry.key === key)?.name?.value ??
    t("unnamed");
  const language = (code: string): string =>
    new Intl.DisplayNames(locale, { type: "language" }).of(code) ?? code;
  /** The place, person or offer a field belongs to, by its name. */
  const subject = ([list, key]: string[]): string | undefined =>
    isList(list) && key ? entryName(list, key) : undefined;
  const label = (path: string[]): string => {
    const leaf = path.at(-1) ?? "";
    // What a kind of booking asks of the company is named where the product
    // has words for it; anything else goes by one neutral label.
    const key = path[2] === "inputs" ? `input_${leaf}` : `field_${leaf}`;
    return t.has(key) ? t(key) : t("inputOther");
  };
  /** A field in words, with whose it is: „Czas trwania — Strzyżenie”. */
  const named = (path: string[]): string => {
    const whose = subject(path);
    if (whose === undefined) return label(path);
    return path.length === 2
      ? whose
      : t("fieldOf", { field: label(path), subject: whose });
  };
  /** A value as a person reads it. */
  const words = (path: string[], value: unknown): string => {
    const leaf = path.at(-1) ?? "";
    if (path[2] !== "inputs") {
      if (leaf === "languages") {
        return (value as string[]).map(language).join(", ");
      }
      if (leaf === "hours") {
        const week = [...(value as Rule[])].sort(
          (a, b) => a.weekday - b.weekday || a.start.localeCompare(b.start),
        );
        const lines = week.map((rule) =>
          t("hoursLine", {
            // 1 January 2024 was a Monday, the profile's weekday 0.
            day: format.dateTime(
              new Date(Date.UTC(2024, 0, 1 + rule.weekday)),
              {
                weekday: "short",
                timeZone: "UTC",
              },
            ),
            start: rule.start,
            end: rule.end,
            place: entryName("places", rule.place),
          }),
        );
        return lines.join("\n") || t("valueNone");
      }
      if (leaf === "price") {
        const { amount, currency, per } = value as Price;
        return t("price", {
          amount: format.number(Number(amount), {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          }),
          currency,
          per: t(`per_${per}`),
        });
      }
      if (leaf === "places" || leaf === "people") {
        const names = (value as string[]).map((key) => entryName(leaf, key));
        return names.join(", ") || t("valueNone");
      }
      if (leaf === "category" || leaf === "preset") {
        const known =
          leaf === "category" ? setup.labels.categories : setup.labels.presets;
        return known[value as string]?.[locale] || t("valueUnknown");
      }
      if (leaf === "duration_minutes") {
        return t("valueMinutes", { count: value as number });
      }
    }
    if (typeof value === "boolean") return t(value ? "valueYes" : "valueNo");
    return typeof value === "object" ? JSON.stringify(value) : String(value);
  };
  /** What a step is about, in words: `place:salon` → miejsce „Salon”. */
  const thing = (ref: string): string => {
    const [kind, key = ""] = ref.split(":");
    const list = REF_LISTS[kind];
    if (list) return t(`thing_${kind}`, { name: entryName(list, key) });
    return t.has(`thing_${kind}`) ? t(`thing_${kind}`) : t("thing_other");
  };
  const asked = (question: AssistantSetupQuestion): string => {
    const path = question.field.split(".");
    if (question.kind === "confirm") {
      return t("confirmLine", { field: named(path) });
    }
    const whose = subject(path);
    // Only a category is proposed: a key, said by its label or not at all.
    const proposal =
      typeof question.proposal === "string"
        ? setup.labels.categories[question.proposal]?.[locale]
        : undefined;
    let key = `ask_${question.reason}`;
    // Nobody to name yet: the question is about the company as a whole.
    if (whose === undefined && t.has(`${key}_any`)) key = `${key}_any`;
    else if (proposal && t.has(`${key}_proposed`)) key = `${key}_proposed`;
    if (!t.has(key)) return t("askOther", { field: named(path) });
    return t(key, {
      name: whose ?? "",
      field: label(path),
      proposal: proposal ?? "",
    });
  };
  const waits = (step: AssistantSetup["waiting"][number]): string => {
    if (step.reason === "person_only") {
      const [, key = ""] = step.ref.split(":");
      return t("waiting_person_only", { name: entryName("offers", key) });
    }
    return t(`waiting_${step.reason}`, {
      thing: thing(step.ref),
      after: step.waits_for.map(thing).join(", "),
    });
  };
  const cannot = (entry: AssistantSetup["unsupported"][number]): string => {
    const path = entry.field.split(".");
    const key = `unsupported_${entry.code}`;
    if (!t.has(key)) return t("unsupportedOther", { field: named(path) });
    return t(key, {
      name: subject(path) ?? "",
      // The languages come as codes: „en, de”.
      detail: entry.code.startsWith("language_")
        ? entry.detail.split(", ").map(language).join(", ")
        : entry.detail,
    });
  };

  const row = (path: string[], said: Said): Row => ({
    path,
    said,
    label: label(path),
    name: named(path),
    text: words(path, said.value),
    edit: editable(path),
  });
  const company = [
    ...(["company", "card"] as const).flatMap((section) =>
      FIELDS[section].flatMap((field) => {
        const said = profile[section]?.[field];
        return said ? [row([section, field], said)] : [];
      }),
    ),
    ...(profile.languages ? [row(["languages"], profile.languages)] : []),
  ];
  const entries = (list: ListName) =>
    (profile[list] ?? []).map((entry) => ({
      key: entry.key,
      title: entry.name?.value ?? t("unnamed"),
      // What the account already has would come back with the next read.
      removable: entry.name?.origin !== "account",
      rows: [
        ...FIELDS[list].flatMap((field) => {
          const said = entry[field] as Said | undefined;
          return said ? [row([list, entry.key, field], said)] : [];
        }),
        ...Object.entries(entry.inputs ?? {}).map(([input, said]) =>
          row([list, entry.key, "inputs", input], said),
        ),
      ],
    }));
  const value = (shown: Row) => (
    <Value
      busy={busy}
      key={shown.path.join(".")}
      onChange={(said) => onSave(patch(profile, shown.path, said))}
      row={shown}
    />
  );
  const blocks = LISTS.map((list) => ({ list, shown: entries(list) }));
  const rows = [
    ...company,
    ...blocks.flatMap((block) => block.shown.flatMap((entry) => entry.rows)),
  ];
  const noted = rows.length > 0 || blocks.some((block) => block.shown.length);

  return (
    <>
      <section className="space-y-3">
        <h2 className="font-medium">{t("knownTitle")}</h2>
        {noted ? null : (
          <p className="text-muted-foreground">{t("knownEmpty")}</p>
        )}
        {rows.some((shown) => shown.said.origin === "account") ? (
          <p className="text-muted-foreground">{t("knownAccountNote")}</p>
        ) : null}
        {company.length ? (
          <Group title={t("group_company")}>
            <dl>{company.map(value)}</dl>
          </Group>
        ) : null}
        {blocks.map(({ list, shown }) =>
          shown.length ? (
            <Group key={list} title={t(`group_${list}`)}>
              {shown.map((entry) => (
                <div className="rounded-lg border px-3 py-1" key={entry.key}>
                  <div className="flex min-h-9 items-center justify-between gap-2">
                    <h4 className="min-w-0 font-medium wrap-anywhere">
                      {entry.title}
                    </h4>
                    {entry.removable ? (
                      <Button
                        aria-label={t("actionRemoveNamed", {
                          field: thing(`${KINDS[list]}:${entry.key}`),
                        })}
                        disabled={busy}
                        onClick={() =>
                          void onSave(withoutEntry(profile, list, entry.key))
                        }
                        size="sm"
                        type="button"
                        variant="ghost"
                      >
                        {t("actionRemove")}
                      </Button>
                    ) : null}
                  </div>
                  {entry.rows.length ? <dl>{entry.rows.map(value)}</dl> : null}
                </div>
              ))}
            </Group>
          ) : null,
        )}
      </section>
      <Lines lines={setup.questions.map(asked)} title={t("questionsTitle")} />
      <Lines
        lines={setup.ready.map((step) => {
          const [kind, key] = step.ref.split(":");
          const list = REF_LISTS[kind];
          return list && key
            ? t("readyNamed", {
                title: step.title[locale],
                name: entryName(list, key),
              })
            : step.title[locale];
        })}
        note={t("readyNote")}
        title={t("readyTitle")}
      />
      <Lines lines={setup.waiting.map(waits)} title={t("waitingTitle")} />
      <Lines
        lines={setup.unsupported.map(cannot)}
        title={t("unsupportedTitle")}
      />
    </>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-muted-foreground uppercase">
        {title}
      </h3>
      {children}
    </div>
  );
}

/** Plain sentences under a title; nothing when there are none. */
function Lines({
  title,
  lines,
  note,
}: {
  title: string;
  lines: string[];
  note?: string;
}) {
  if (!lines.length) return null;
  return (
    <section className="space-y-2">
      <h2 className="font-medium">{title}</h2>
      <ul className="list-disc space-y-1 pl-5">
        {lines.map((line, index) => (
          <li key={index}>{line}</li>
        ))}
      </ul>
      {note ? <p className="text-muted-foreground">{note}</p> : null}
    </section>
  );
}

/** One value: what it is, where it came from, and what can be done with it. */
function Value({
  row,
  busy,
  onChange,
}: {
  row: Row;
  busy: boolean;
  /** The value to keep, or null to remove it; answers whether it was saved. */
  onChange: (said: Said | null) => Promise<boolean>;
}) {
  const t = useTranslations("Assistant");
  const [draft, setDraft] = useState<string>();
  const closed = useRef(false);
  const { said } = row;
  // A fact of the account is changed in the panel's own settings; taken out
  // here it would come back with the next read.
  const fact = said.origin === "account";
  const typed = draft?.trim() ?? "";
  const valid = row.edit === "number" ? /^\d+$/.test(typed) : typed !== "";

  // Closing the input gives the focus back to the button that opened it.
  const opener = useCallback((node: HTMLElement | null) => {
    if (node && closed.current) {
      closed.current = false;
      node.focus();
    }
  }, []);

  function close() {
    closed.current = true;
    setDraft(undefined);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid || busy) return;
    const value = row.edit === "number" ? Number(typed) : typed;
    // The person typed it: it is theirs, and confirmed.
    if (await onChange({ value, origin: "owner", confirmed: true })) close();
  }

  const field = {
    "aria-label": row.name,
    autoFocus: true,
    onChange: (event: { target: { value: string } }) =>
      setDraft(event.target.value),
    onKeyDown: (event: { key: string }) => {
      if (event.key === "Escape") close();
    },
    value: draft ?? "",
  };

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t py-1.5 first:border-t-0">
      <dt className="w-40 shrink-0 text-muted-foreground">{row.label}</dt>
      {draft === undefined ? (
        <dd className="flex min-w-0 flex-1 basis-56 flex-wrap items-center gap-x-2 gap-y-1">
          <span className="min-w-0 wrap-anywhere whitespace-pre-line">
            {row.text}
          </span>
          <Badge variant="neutral">{t(`origin_${said.origin}`)}</Badge>
          {said.confirmed ? null : (
            <Badge variant="warning">{t("unconfirmed")}</Badge>
          )}
          <span className="ml-auto flex flex-wrap items-center gap-0.5">
            {said.confirmed ? null : (
              <Button
                aria-label={t("actionConfirmNamed", { field: row.name })}
                disabled={busy}
                onClick={() =>
                  void onChange({ ...said, origin: "owner", confirmed: true })
                }
                size="sm"
                type="button"
                variant="ghost"
              >
                {t("actionConfirm")}
              </Button>
            )}
            {row.edit && !fact ? (
              <Button
                aria-label={t("actionEditNamed", { field: row.name })}
                disabled={busy}
                onClick={() => setDraft(String(said.value))}
                ref={opener}
                size="sm"
                type="button"
                variant="ghost"
              >
                {t("actionEdit")}
              </Button>
            ) : null}
            {fact ? null : (
              <Button
                aria-label={t("actionRemoveNamed", { field: row.name })}
                disabled={busy}
                onClick={() => void onChange(null)}
                size="sm"
                type="button"
                variant="ghost"
              >
                {t("actionRemove")}
              </Button>
            )}
          </span>
        </dd>
      ) : (
        <dd className="min-w-0 flex-1 basis-56">
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(event) => void submit(event)}
          >
            {row.edit === "long" ? (
              <Textarea className="min-w-0 flex-1 basis-56" {...field} />
            ) : (
              <Input
                className="h-9 min-w-0 flex-1 basis-40"
                inputMode={row.edit === "number" ? "numeric" : undefined}
                {...field}
              />
            )}
            <Button disabled={busy || !valid} size="sm" type="submit">
              {t("actionSave")}
            </Button>
            <Button
              disabled={busy}
              onClick={close}
              size="sm"
              type="button"
              variant="ghost"
            >
              {t("actionCancel")}
            </Button>
          </form>
        </dd>
      )}
    </div>
  );
}
