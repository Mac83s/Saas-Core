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
import { ChevronRightIcon, EllipsisIcon } from "lucide-react";

import {
  ApiProblemError,
  changeAssistantProfile,
  getAssistantSetup,
  type AssistantSetup,
  type AssistantSetupQuestion,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@saas-core/ui/components/dropdown-menu";
import { Input } from "@saas-core/ui/components/input";
import { Textarea } from "@saas-core/ui/components/textarea";

import { dateFormat, formatDateRange, formatHours } from "#lib/dates";

type Locale = "pl" | "en";
type Origin =
  "owner" | "account" | "existing_site" | "preset_default" | "assistant";
/** One value of the notes: what was said, by whom, and whether the owner
 *  confirmed it. */
type Said<T = unknown> = { value: T; origin: Origin; confirmed: boolean };
type Rule = { weekday: number; start: string; end: string; place: string };
type Price = { amount: string; currency: string; per: string };
/** A stay's season as the owner said it: its days, and the rules named. */
type Season = {
  name?: string;
  starts_on: string;
  ends_on: string;
  min_stay?: number;
  arrival_days?: number[];
};
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
  /** Where it lives: `company.city`, `offers.cut.inputs.min_length`. */
  path: string[];
  label: string;
  /** The label with whose it is; what the row's controls are named by. */
  name: string;
  text: string;
  said: Said;
  /** What „Popraw” takes: text, a longer text or a whole number. */
  edit?: "text" | "long" | "number";
};
/**
 * Where the focus goes once a change is saved and the notes are read again.
 * Rows and entries are found by their place in the group, not by their keys:
 * a key is never written into the page.
 */
type Focus =
  /** The „…” of the confirmed row: the row at `menu` in the block at `block`. */
  | { group: string; block: number; menu: number }
  /** What follows a removed row (in the block at `block`) or a removed entry. */
  | { group: string; block?: number; index: number };
/** What a saved change is followed by: the line that says so, and the focus. */
type Outcome = { notice: string; focus?: Focus };

const LISTS = ["places", "people", "offers"] as const;
type ListName = (typeof LISTS)[number];
/** The values of each part of the notes, in the order they are shown. */
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
    "vat",
    "seasons",
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
  units: "offers",
  price: "offers",
  season: "offers",
};
const CONFLICT = "assistant_profile_version_conflict";
/** A row's button: 44 px on a phone, the row's height from md — as the
 *  panel's tables have it. */
const ROW_BUTTON = "md:h-9 md:px-3";

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
 * places and people of the account, which the saved notes may not — a list
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

/** The element a saved change hands the focus to, in the notes as they are now. */
function seek(root: HTMLElement | null, focus: Focus): HTMLElement | null {
  const group = root?.querySelector(`[data-group="${focus.group}"]`);
  const blocks = Array.from(group?.querySelectorAll("[data-block]") ?? []);
  const rows = (block: number) =>
    Array.from(blocks[block]?.querySelectorAll("[data-row]") ?? []);
  if ("menu" in focus) {
    const row = rows(focus.block)[focus.menu];
    return row?.querySelector<HTMLElement>("[data-row-menu]") ?? null;
  }
  // What stood after the removed row or entry stands in its place now.
  const stops = focus.block === undefined ? blocks : rows(focus.block);
  for (const stop of stops.slice(focus.index)) {
    const control = stop.querySelector<HTMLElement>("button");
    if (control) return control;
  }
  // Nothing follows: the group's heading, or the section's once the group is gone.
  return (
    group?.querySelector<HTMLElement>("h3") ??
    root?.querySelector<HTMLElement>("h2") ??
    null
  );
}

/**
 * The assistant's notes about the company beside a setup conversation
 * (ADR-076, A3-2): what is known and from whom, what the assistant will still
 * ask, what is ready, what is left for later and what cannot be set up yet.
 * A value can be confirmed, corrected or removed here. That changes the notes
 * only — what was said, not the account; a plan still waits for the click in
 * the consent dialog.
 *
 * Nothing is shown by its key: a category, a kind of booking, an entry and a
 * field are said in words, or by a neutral text where there are none.
 */
/**
 * The room the notes have beside the conversation: from where the block sits
 * now — its place in the page, then under the panel's header once the page
 * has scrolled — down to the bottom of the window. They are read whole without
 * scrolling the page, and scroll on their own.
 */
function useRoomBelow(active: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node || !active) return;
    const fit = () => {
      const room = window.innerHeight - node.getBoundingClientRect().top - 16;
      node.style.maxHeight = `${Math.max(room, 160)}px`;
    };
    fit();
    window.addEventListener("scroll", fit, { passive: true });
    window.addEventListener("resize", fit);
    return () => {
      window.removeEventListener("scroll", fit);
      window.removeEventListener("resize", fit);
      node.style.maxHeight = "";
    };
  }, [active]);
  return ref;
}

export function SetupProfile({
  conversationId,
  revision,
  beside = false,
}: {
  conversationId: string;
  /** Changes when the conversation settles: the notes are read again. */
  revision: number;
  /**
   * Beside the conversation on a wide screen: open, with its own scroll.
   * Otherwise under the conversation, closed until the person opens it.
   */
  beside?: boolean;
}) {
  const t = useTranslations("Assistant");
  const [setup, setSetup] = useState<AssistantSetup>();
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [problem, setProblem] = useState<string>();
  const [outcome, setOutcome] = useState<Outcome>();
  const [busy, setBusy] = useState(false);
  const room = useRoomBelow(beside);

  useEffect(() => {
    const controller = new AbortController();
    getAssistantSetup(conversationId, controller.signal)
      .then((next) => {
        setSetup(next);
        setFailed(false);
      })
      .catch(() => {
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [conversationId, revision, attempt]);

  /** Saves against the version shown, then shows what the notes hold. */
  async function save(changes: Changes, done: Outcome): Promise<boolean> {
    if (!setup || busy) return false;
    setBusy(true);
    setProblem(undefined);
    setOutcome(undefined);
    try {
      await changeAssistantProfile(changes, setup.version, crypto.randomUUID());
      setSetup(await getAssistantSetup(conversationId));
      setOutcome(done);
      return true;
    } catch (error) {
      const moved =
        error instanceof ApiProblemError && error.problem.code === CONFLICT;
      if (moved) {
        // The assistant, or another window, changed them first: show theirs.
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

  const count = (kind: AssistantSetupQuestion["kind"]) =>
    setup?.questions.filter((question) => question.kind === kind).length ?? 0;
  const body = (
    <>
      <p className="text-muted-foreground">{t("notesHint")}</p>
      {failed ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-destructive">{t("profileLoadError")}</p>
          <Button
            onClick={() => setAttempt((tries) => tries + 1)}
            type="button"
            variant="outline"
          >
            {t("retry")}
          </Button>
        </div>
      ) : null}
      {problem ? (
        <p className="text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      {setup ? (
        <>
          <p className="text-success-foreground empty:hidden" role="status">
            {outcome?.notice}
          </p>
          <Overview
            busy={busy}
            focus={outcome?.focus}
            onSave={save}
            setup={setup}
          />
        </>
      ) : failed ? null : (
        <p className="text-muted-foreground" role="status">
          {t("profileLoading")}
        </p>
      )}
    </>
  );

  if (beside) {
    return (
      // Stays in view beside a long conversation, under the panel's header
      // (68 px). The anchor has no height of its own, so the notes never make
      // the page longer than the conversation; `useRoomBelow` keeps them
      // inside the window.
      <div className="xl:sticky xl:top-21 xl:h-0">
        <div
          className="space-y-4 rounded-lg border bg-background p-4 text-sm xl:max-h-[calc(100dvh-6.25rem)] xl:overflow-y-auto"
          ref={room}
        >
          <p className="font-medium">{t("profileTitle")}</p>
          {body}
        </div>
      </div>
    );
  }
  // Closed, the line says whether the notes need the person.
  const toConfirm = count("confirm");
  const questions = count("ask");
  const summary = [
    t("summaryTitle"),
    ...(toConfirm ? [t("summaryToConfirm", { count: toConfirm })] : []),
    ...(questions ? [t("summaryQuestions", { count: questions })] : []),
  ].join(" · ");
  return (
    <details className="group rounded-lg border text-sm">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1.5 px-4 py-2 font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRightIcon
          aria-hidden="true"
          className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-90"
        />
        {summary}
      </summary>
      <div className="space-y-4 border-t px-4 py-3">{body}</div>
    </details>
  );
}

function Overview({
  setup,
  busy,
  focus,
  onSave,
}: {
  setup: AssistantSetup;
  busy: boolean;
  /** Where the last saved change hands the focus to. */
  focus?: Focus;
  onSave: (changes: Changes, done: Outcome) => Promise<boolean>;
}) {
  const t = useTranslations("Assistant");
  const locale = useLocale() as Locale;
  const format = useFormatter();
  const profile = setup.document as Profile;
  const root = useRef<HTMLDivElement>(null);
  /** The entry the person is asked about before it is removed. */
  const [asking, setAsking] = useState<{
    list: ListName;
    key: string;
    index: number;
  }>();

  // A saved change took its own control away, or disabled it for a moment:
  // the focus goes on to what the person would reach for next.
  useEffect(() => {
    if (focus) seek(root.current, focus)?.focus();
  }, [focus]);

  const nameOf = (list: ListName, key: string): string | undefined =>
    profile[list]?.find((entry) => entry.key === key)?.name?.value;
  // A key is the document's own name for an entry: a person never reads one.
  const entryName = (list: ListName, key: string): string =>
    nameOf(list, key) ?? t("unnamed");
  /** An entry inside a sentence: its name in quotes, a nameless one in words. */
  const quoted = (list: ListName, key: string): string => {
    const name = nameOf(list, key);
    return name === undefined ? t("unnamed") : t("quoted", { name });
  };
  const language = (code: string): string =>
    new Intl.DisplayNames(locale, { type: "language" }).of(code) ?? code;
  /** The place, person or offer a field belongs to: by its name, and as a
   *  sentence says it. */
  const subject = ([list, key]: string[]) =>
    isList(list) && key
      ? { plain: entryName(list, key), quoted: quoted(list, key) }
      : undefined;
  const label = (path: string[]): string => {
    const leaf = path.at(-1) ?? "";
    // What a kind of booking asks of the company is named where there are
    // words for it; anything else goes by one neutral label.
    const key = path[2] === "inputs" ? `input_${leaf}` : `field_${leaf}`;
    return t.has(key) ? t(key) : t("inputOther");
  };
  /** A field in words, with whose it is: „Czas trwania — Strzyżenie”. */
  const named = (path: string[]): string => {
    const whose = subject(path)?.plain;
    if (whose === undefined) return label(path);
    return path.length === 2
      ? whose
      : t("fieldOf", { field: label(path), subject: whose });
  };
  /** A value as a person reads it. */
  const words = (path: string[], value: unknown): string => {
    const leaf = path.at(-1) ?? "";
    if (path[2] === "inputs") {
      if (leaf === "min_length" && typeof value === "number") {
        return t("valueNights", { count: value });
      }
    } else {
      if (leaf === "languages") {
        return (value as string[]).map(language).join(", ");
      }
      if (leaf === "hours") {
        const week = [...(value as Rule[])].sort(
          (a, b) => a.weekday - b.weekday || a.start.localeCompare(b.start),
        );
        // 1 January 2024 was a Monday, the notes' weekday 0.
        const at = (rule: Rule, time: string) =>
          new Date(`2024-01-0${1 + rule.weekday}T${time}:00Z`);
        const lines = week.map((rule) =>
          t("hoursLine", {
            day: dateFormat(locale, {
              weekday: "short",
              timeZone: "UTC",
            }).format(at(rule, rule.start)),
            hours: formatHours(
              at(rule, rule.start),
              at(rule, rule.end),
              locale,
              "UTC",
            ),
            place: entryName("places", rule.place),
          }),
        );
        return lines.join("\n") || t("valueNone");
      }
      if (leaf === "price") {
        const { amount, currency, per } = value as Price;
        return t("price", {
          amount: format.number(Number(amount), {
            style: "currency",
            currency,
          }),
          per: t(`per_${per}`),
        });
      }
      if (leaf === "seasons") {
        // 1 January 2024 was a Monday, the notes' weekday 0.
        const weekday = (day: number) =>
          dateFormat(locale, { weekday: "short", timeZone: "UTC" }).format(
            new Date(`2024-01-0${1 + day}T12:00:00Z`),
          );
        const lines = (value as Season[]).map((season) => {
          const dates = formatDateRange(
            season.starts_on,
            season.ends_on,
            locale,
          );
          const rules = [
            season.min_stay
              ? t("seasonMinStay", { count: season.min_stay })
              : "",
            season.arrival_days?.length
              ? t("seasonArrival", {
                  days: season.arrival_days.map(weekday).join(", "),
                })
              : "",
          ].filter(Boolean);
          const head = season.name
            ? t("seasonNamed", { name: season.name, dates })
            : dates;
          return rules.length
            ? t("seasonLine", { dates: head, rules: rules.join(", ") })
            : head;
        });
        return lines.join("\n") || t("valueNone");
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
      if (leaf === "vat" && t.has(`vat_${String(value)}`)) {
        return t(`vat_${String(value)}`);
      }
    }
    if (typeof value === "boolean") return t(value ? "valueYes" : "valueNo");
    // An answer with a shape of its own has no words here: it is noted.
    return typeof value === "object" ? t("valueNoted") : String(value);
  };
  /** What a step is about, in words: `place:salon` → miejsce „Salon”. */
  const thing = (ref: string): string => {
    const [kind, key = ""] = ref.split(":");
    const list = REF_LISTS[kind];
    if (list) return t(`thing_${kind}`, { name: quoted(list, key) });
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
      name: whose?.quoted ?? "",
      person: whose?.plain ?? "",
      field: label(path),
      proposal: proposal ?? "",
    });
  };
  const waits = (step: AssistantSetup["waiting"][number]): string => {
    if (step.reason === "person_only") {
      const [, key = ""] = step.ref.split(":");
      return t("waiting_person_only", { name: quoted("offers", key) });
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
      name: subject(path)?.quoted ?? "",
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
      title: entry.name?.value ?? t("unnamedHeading"),
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
  /** The rows of one block: each knows where the focus goes when it is gone. */
  const values = (group: string, block: number, shown: Row[]) => (
    <dl>
      {shown.map((item, index) => {
        const save = (said: Said | null, done: Outcome) =>
          onSave(patch(profile, item.path, said), done);
        return (
          <Value
            busy={busy}
            key={item.path.join(".")}
            onConfirm={() =>
              // The same value, now the owner's own: its „Potwierdź” is gone.
              save(
                { ...item.said, origin: "owner", confirmed: true },
                { notice: t("saved"), focus: { group, block, menu: index } },
              )
            }
            onCorrect={(value) =>
              save(
                { value, origin: "owner", confirmed: true },
                { notice: t("saved") },
              )
            }
            onRemove={() =>
              save(null, {
                notice: t("removed", { field: item.name }),
                focus: { group, block, index },
              })
            }
            row={item}
          />
        );
      })}
    </dl>
  );
  const blocks = LISTS.map((list) => ({ list, shown: entries(list) }));
  const rows = [
    ...company,
    ...blocks.flatMap((block) => block.shown.flatMap((entry) => entry.rows)),
  ];
  const noted = rows.length > 0 || blocks.some((block) => block.shown.length);
  const asks = asking ? `${KINDS[asking.list]}:${asking.key}` : "";

  return (
    <div className="space-y-5" ref={root}>
      <section className="space-y-3">
        <h2 className="font-medium" tabIndex={-1}>
          {t("knownTitle")}
        </h2>
        {noted ? null : (
          <p className="text-muted-foreground">{t("knownEmpty")}</p>
        )}
        {rows.some((shown) => shown.said.origin === "account") ? (
          <p className="text-muted-foreground">{t("knownAccountNote")}</p>
        ) : null}
        {company.length ? (
          <Group id="company" title={t("group_company")}>
            <div data-block="">{values("company", 0, company)}</div>
          </Group>
        ) : null}
        {blocks.map(({ list, shown }) =>
          shown.length ? (
            <Group id={list} key={list} title={t(`group_${list}`)}>
              {shown.map((entry, index) => (
                <div
                  className="rounded-lg border px-3 py-1"
                  data-block=""
                  key={entry.key}
                >
                  <div className="flex min-h-11 items-center justify-between gap-2 md:min-h-9">
                    <h4 className="min-w-0 font-medium wrap-anywhere">
                      {entry.title}
                    </h4>
                    {entry.removable ? (
                      <Button
                        aria-label={t("actionRemoveNamed", {
                          field: thing(`${KINDS[list]}:${entry.key}`),
                        })}
                        className={ROW_BUTTON}
                        disabled={busy}
                        onClick={() =>
                          setAsking({ list, key: entry.key, index })
                        }
                        type="button"
                        variant="ghost"
                      >
                        {t("actionRemove")}
                      </Button>
                    ) : null}
                  </div>
                  {entry.rows.length ? values(list, index, entry.rows) : null}
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
          // The notes name what a step is about; where they no longer do —
          // the draft of a service taken out of them — the step does.
          const name = list && key ? entryName(list, key) : step.name;
          const line = name
            ? t("readyNamed", { title: step.title[locale], name })
            : step.title[locale];
          return step.risk === "irreversible"
            ? t("readyIrreversible", { line })
            : line;
        })}
        note={t("readyNote")}
        title={t("readyTitle")}
      />
      <Lines lines={setup.waiting.map(waits)} title={t("waitingTitle")} />
      <Lines
        lines={setup.unsupported.map(cannot)}
        title={t("unsupportedTitle")}
      />
      {/* A whole place, person or offer takes more with it than its own
          values, so it asks first; an outside click is not an answer. */}
      <Dialog
        disablePointerDismissal
        onOpenChange={(open) => {
          if (!open) setAsking(undefined);
        }}
        open={Boolean(asking)}
      >
        <DialogContent role="alertdialog" showCloseButton={false}>
          {asking ? (
            <>
              <DialogHeader>
                <DialogTitle>
                  {t(`removeEntryTitle_${KINDS[asking.list]}`, {
                    name: quoted(asking.list, asking.key),
                  })}
                </DialogTitle>
                <DialogDescription>
                  {t(`removeEntryText_${KINDS[asking.list]}`)}
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <DialogClose render={<Button variant="outline" />}>
                  {t("actionCancel")}
                </DialogClose>
                <Button
                  onClick={() => {
                    setAsking(undefined);
                    void onSave(
                      withoutEntry(profile, asking.list, asking.key),
                      {
                        notice: t("removed", { field: thing(asks) }),
                        focus: { group: asking.list, index: asking.index },
                      },
                    );
                  }}
                  type="button"
                  variant="destructive"
                >
                  {t("removeEntryConfirm")}
                </Button>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** One group of what is known; its heading takes the focus when the last of
 *  its rows is removed. */
function Group({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2" data-group={id}>
      <h3
        className="text-xs font-medium text-muted-foreground uppercase"
        tabIndex={-1}
      >
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

/**
 * One value: what it is, where it came from, and what can be done with it.
 * One action is in sight — „Potwierdź”, while the value waits for it; the
 * rest is behind „…”, as in the panel's tables.
 */
function Value({
  row,
  busy,
  onConfirm,
  onCorrect,
  onRemove,
}: {
  row: Row;
  busy: boolean;
  onConfirm: () => Promise<boolean>;
  /** Answers whether the typed value was saved. */
  onCorrect: (value: string | number) => Promise<boolean>;
  onRemove: () => Promise<boolean>;
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

  // Closing the input gives the focus back to the „…” that opened it.
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
    // The person typed it: it is theirs, and confirmed.
    if (await onCorrect(row.edit === "number" ? Number(typed) : typed)) close();
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
    // The label wraps over the value wherever the block is narrow: on a
    // phone, and beside the conversation.
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t py-1.5 first:border-t-0"
      data-row=""
    >
      <dt className="w-40 shrink-0 text-muted-foreground">{row.label}</dt>
      {draft === undefined ? (
        <dd className="flex min-w-0 flex-1 basis-56 flex-wrap items-center gap-x-2 gap-y-1">
          <span className="min-w-0 wrap-anywhere whitespace-pre-line">
            {row.text}
          </span>
          {/* The owner's own word is what a value is unless it says otherwise. */}
          {said.origin === "owner" ? null : (
            <span className="text-xs text-muted-foreground">
              {t(`origin_${said.origin}`)}
            </span>
          )}
          {said.confirmed ? null : (
            <Badge variant="warning">{t("unconfirmed")}</Badge>
          )}
          <span className="ml-auto flex items-center gap-0.5">
            {said.confirmed ? null : (
              <Button
                aria-label={t("actionConfirmNamed", { field: row.name })}
                className={ROW_BUTTON}
                disabled={busy}
                onClick={() => void onConfirm()}
                type="button"
                variant="outline"
              >
                {t("actionConfirm")}
              </Button>
            )}
            {fact ? null : (
              <DropdownMenu>
                <DropdownMenuTrigger
                  data-row-menu=""
                  disabled={busy}
                  ref={opener}
                  render={
                    <Button
                      aria-label={t("actionMore", { field: row.name })}
                      className="md:size-9"
                      size="icon"
                      variant="ghost"
                    />
                  }
                >
                  <EllipsisIcon aria-hidden="true" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {row.edit ? (
                    <>
                      <DropdownMenuItem
                        onClick={() => setDraft(String(said.value))}
                      >
                        {t("actionEdit")}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                    </>
                  ) : null}
                  <DropdownMenuItem
                    className="text-destructive"
                    onClick={() => void onRemove()}
                  >
                    {t("actionRemove")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
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
                className="min-w-0 flex-1 basis-40 md:h-9"
                inputMode={row.edit === "number" ? "numeric" : undefined}
                {...field}
              />
            )}
            <Button
              className={ROW_BUTTON}
              disabled={busy || !valid}
              type="submit"
            >
              {t("actionSave")}
            </Button>
            <Button
              className={ROW_BUTTON}
              disabled={busy}
              onClick={close}
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
