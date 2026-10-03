"use client";

/** The page editor in another language (TL15). The source decides the
 *  structure — sections, images, links, layout — and this mode edits only
 *  the words: one row per fragment, the source's text beside the field
 *  (two columns from 1024 px, one under the other on a phone). Saving sends
 *  only what changed, against this language's own version; after a conflict
 *  the new version loads and the unsaved words go back on top of it. */

import {
  acceptLocaleBody,
  ApiProblemError,
  getLocaleBody,
  getLocaleBodyVersion,
  listLocaleBodyVersions,
  listPageTranslations,
  previewPublishLocaleBody,
  previewRebaseLocaleBody,
  publishLocaleBody,
  rebaseLocaleBody,
  rejectLocaleBody,
  restoreLocaleBodyVersion,
  saveLocaleBody,
  savePageTranslation,
  withdrawLocaleBody,
  type LanguageDecision,
  type LocaleBody,
  type LocaleBodyUnit,
  type LocaleBodyVersionList,
  type PageSummary,
  type PageTranslation,
} from "@saas-core/api-client";
import {
  renderDraftPreview,
  type BlockFieldDefinition,
  type SiteAppearance,
} from "@saas-core/site-blocks";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@saas-core/ui/components/dropdown-menu";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { Textarea } from "@saas-core/ui/components/textarea";
import {
  EllipsisIcon,
  EyeIcon,
  HistoryIcon,
  SaveIcon,
  Settings2Icon,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useShown } from "#lib/use-shown";

import {
  blockOptions,
  registry,
  toSiteBlock,
  useSectionTypeName,
} from "./block-form";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { privateMediaRenderer } from "./private-media-preview";
import {
  TranslateDialog,
  TranslationUnavailable,
} from "../translation/translate-dialog";
import {
  translationJobFinished,
  useTranslationJob,
  useTranslationOffer,
} from "../translation/use-translation";
import { TokenText, TokenTextField } from "./rich-text-token-field";
import { SeoPreview } from "./seo-preview";
import type { TokenMarks } from "./rich-text-tokens";
import { slugFromTitle } from "./slug";

const designTokens = {
  schemaVersion: 1,
  palette: "neutral",
  typography: "sans",
  radius: "medium",
  spacing: "comfortable",
} as const;

type Values = Record<string, string>;

/** What the field starts with: the stored text, or — for a run with
 *  formatting — the source's, so its tokens are there to move. */
function initialValue(unit: LocaleBodyUnit): string {
  if (unit.text !== null) return unit.text;
  return unit.kind === "inline" ? unit.source_text : "";
}

function initialValues(body: LocaleBody): Values {
  return Object.fromEntries(
    body.units.map((unit) => [unit.key, initialValue(unit)]),
  );
}

function editable(unit: LocaleBodyUnit): boolean {
  return (unit.kind === "text" || unit.kind === "inline") && !unit.placeholder;
}

interface FieldLabelKeys {
  readonly labelKey: string;
  readonly parentKey?: string;
  readonly index?: number;
  readonly fragment?: number;
}

/** The block catalog's name for the field a unit's key points at:
 *  `1/items/0/question` in an FAQ is "Pytania 1: Pytanie". */
function labelKeys(blockType: string | undefined, path: readonly string[]) {
  const option = blockOptions.find((item) => item.type === blockType);
  const walk = (
    fields: readonly BlockFieldDefinition[],
    parts: readonly string[],
  ): FieldLabelKeys | null => {
    for (const field of fields) {
      const own = field.path;
      const prefix = own.every((part, index) => parts[index] === part);
      if (!prefix) continue;
      const rest = parts.slice(own.length);
      if (rest.length === 0) return { labelKey: field.labelKey };
      if (field.kind === "list" && field.item && /^\d+$/.test(rest[0] ?? "")) {
        const inner = walk(field.item, rest.slice(1));
        return {
          labelKey: inner?.labelKey ?? field.labelKey,
          parentKey: field.labelKey,
          index: Number(rest[0]) + 1,
        };
      }
      // A rich text field holds several runs: name it with the run's place.
      if (/^\d+$/.test(rest[0] ?? "")) {
        return { labelKey: field.labelKey, fragment: Number(rest[0]) + 1 };
      }
    }
    return null;
  };
  return option ? walk(option.fields, path) : null;
}

/** Where the unit's field stands in the block's catalog; unknown ones last,
 *  in their own order (`sort` is stable). */
function fieldOrder(blockType: string | undefined, key: string): number {
  const fields = blockOptions.find((item) => item.type === blockType)?.fields;
  const parts = key.split("/").slice(1);
  const index = (fields ?? []).findIndex((field) =>
    field.path.every((part, position) => parts[position] === part),
  );
  return index === -1 ? Number.MAX_SAFE_INTEGER : index;
}

function problemOf(error: unknown): ApiProblemError["problem"] | null {
  return error instanceof ApiProblemError ? error.problem : null;
}

export interface PageLanguageEditorProps {
  readonly page: PageSummary;
  /** The language shown, never the source. */
  readonly locale: string;
  readonly languageName: string;
  readonly sourceName: string;
  /** What opens the top bar: the studio's way back and the dialog's title,
   *  as in the source's editor. */
  readonly leading?: ReactNode;
  /** The language picker, shown in this mode's toolbar. */
  readonly languageSwitch: ReactNode;
  readonly appearance?: SiteAppearance;
  readonly onSwitchToSource: () => void;
  /** Called after a save, so the language states around refresh. */
  readonly onChanged: () => void;
  readonly onExitStateChange?: (state: {
    dirty: boolean;
    busy: boolean;
  }) => void;
}

export function PageLanguageEditor({
  page,
  locale,
  languageName,
  sourceName,
  leading,
  languageSwitch,
  appearance,
  onSwitchToSource,
  onChanged,
  onExitStateChange,
}: PageLanguageEditorProps) {
  const t = useTranslations("Sites.languageMode");
  const sites = useTranslations("Sites");
  const studio = useTranslations("Sites.studio");
  const common = useTranslations("Common");
  const interfaceLocale = useLocale();
  const [body, setBody] = useState<LocaleBody>();
  const [state, setState] = useState<
    "loading" | "ready" | "no-address" | "not-enabled" | "error"
  >("loading");
  const [values, setValues] = useState<Values>({});
  const [initial, setInitial] = useState<Values>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [started, setStarted] = useState(false);
  const [metadataOpen, setMetadataOpen] = useState(false);
  const [preview, setPreview] = useState<{
    number: number;
    blocks: unknown[];
    waiting: boolean;
  } | null>(null);
  const shownPreview = useShown(preview);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [versions, setVersions] = useState<LocaleBodyVersionList["items"]>();
  const [restoring, setRestoring] = useState<{
    id: string;
    number: number;
  } | null>(null);
  const shownRestoring = useShown(restoring);
  const [rebase, setRebase] = useState<{ untranslated: number } | null>(null);
  const shownRebase = useShown(rebase);
  // While a version waits: only the fragments it changes.
  const [onlyChanged, setOnlyChanged] = useState(false);
  const receipt = useRef<MutationReceipt | undefined>(undefined);
  // A decision on this language version waiting for its confirmation;
  // `blocked` is why it cannot be published yet.
  const [decision, setDecision] = useState<
    | { kind: "accept" | "reject" | "publish" | "withdraw" }
    | { kind: "blocked"; reason: string }
    | null
  >(null);
  const shownDecision = useShown(decision);
  const [deciding, setDeciding] = useState(false);
  // Automatic translation: whether it can be ordered here, the dialog, and
  // the order being followed — it runs on the server whatever this screen
  // does, and the page reloads when it ends.
  const offer = useTranslationOffer();
  const [translating, setTranslating] = useState(false);
  const [jobId, setJobId] = useState<string>();
  const job = useTranslationJob(jobId);

  const dirtyKeys = useMemo(
    () => Object.keys(values).filter((key) => values[key] !== initial[key]),
    [values, initial],
  );
  useEffect(() => {
    onExitStateChange?.({ dirty: dirtyKeys.length > 0, busy: saving });
  }, [dirtyKeys.length, onExitStateChange, saving]);

  /** Loads the language; `keep` are words not yet saved, laid back on top. */
  const load = useCallback(
    async (keep: Values = {}) => {
      try {
        const loaded = await getLocaleBody(page.id, locale);
        const fresh = initialValues(loaded);
        setBody(loaded);
        setInitial(fresh);
        setValues({ ...fresh, ...keep });
        setState("ready");
        return loaded;
      } catch (error) {
        const code = problemOf(error)?.code;
        setState(
          code === "translation_not_found"
            ? "no-address"
            : code === "locale_not_enabled"
              ? "not-enabled"
              : "error",
        );
        return undefined;
      }
    },
    [locale, page.id],
  );
  // The studio keys this editor by page and language, so a new one loads.
  useEffect(() => {
    // Loading from the API sets state only once the answer comes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const jobDone = translationJobFinished(job);
  useEffect(() => {
    if (!jobDone) return;
    // The job wrote this language: show what it wrote. Text that waits for a
    // decision is not a new version yet, and the notice says so.
    const before = body?.version_id ?? null;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load().then((loaded) =>
      setNotice(
        t(
          loaded?.pending && loaded.version_id === before
            ? "actions.translatedWaiting"
            : "actions.translated",
        ),
      ),
    );
    onChanged();
    // `load` and `onChanged` are the same for the editor's life.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobDone]);

  const marks = useMemo(
    () =>
      Object.fromEntries(
        (body?.units ?? []).map((unit) => [
          unit.key,
          (unit.marks ?? []) as TokenMarks[],
        ]),
      ),
    [body],
  );

  async function save() {
    if (!body || dirtyKeys.length === 0) {
      setNotice(t("nothingToSave"));
      return;
    }
    const input = {
      source_version_id: body.source_version_id,
      expected_body_version: body.body_version,
      units: Object.fromEntries(
        dirtyKeys.map((key) => [key, values[key] ?? ""]),
      ),
    };
    setSaving(true);
    setErrors({});
    try {
      const saved = await saveLocaleBody(
        page.id,
        locale,
        input,
        mutationKey(receipt, `locale-body-${page.id}-${locale}`, input),
      );
      receipt.current = undefined;
      const fresh = initialValues(saved);
      setBody(saved);
      setInitial(fresh);
      setValues(fresh);
      setNotice(t("saved", { language: languageName }));
      onChanged();
    } catch (error) {
      const problem = problemOf(error);
      if (
        problem?.code === "locale_body_version_conflict" ||
        problem?.code === "source_version_mismatch"
      ) {
        receipt.current = undefined;
        const keep = Object.fromEntries(
          dirtyKeys.map((key) => [key, values[key] ?? ""]),
        );
        await load(keep);
        setNotice(t("conflict"));
      } else if (problem?.errors?.length) {
        setErrors(
          Object.fromEntries(
            problem.errors
              .filter((item) => item.field?.startsWith("units."))
              .map((item) => [item.field!.slice("units.".length), item.code]),
          ),
        );
      } else {
        setNotice(
          error instanceof Error ? error.message : t("unitErrors.other"),
        );
      }
    } finally {
      setSaving(false);
    }
  }

  async function openPreview() {
    // What the fields show: the version that waits, else the language's own.
    const versionId = waiting ? body?.pending?.version_id : body?.version_id;
    if (!versionId) return;
    const shown = await getLocaleBodyVersion(page.id, locale, versionId);
    setPreview({
      number: shown.version.number,
      blocks: shown.blocks,
      waiting,
    });
  }

  async function openHistory() {
    setHistoryOpen(true);
    setVersions((await listLocaleBodyVersions(page.id, locale)).items);
  }

  async function confirmRestore() {
    if (!restoring || !body) return;
    const restored = await restoreLocaleBodyVersion(
      page.id,
      locale,
      restoring.id,
      body.body_version,
      crypto.randomUUID(),
    );
    const fresh = initialValues(restored);
    setBody(restored);
    setInitial(fresh);
    setValues(fresh);
    setNotice(
      t("restored", { from: restoring.number, number: restored.version ?? 0 }),
    );
    setRestoring(null);
    setHistoryOpen(false);
    onChanged();
  }

  async function askRebase() {
    if (!body) return;
    const planned = await previewRebaseLocaleBody(
      page.id,
      locale,
      body.body_version,
    );
    setRebase({ untranslated: planned.untranslated });
  }

  async function confirmRebase() {
    if (!body) return;
    const moved = await rebaseLocaleBody(
      page.id,
      locale,
      body.body_version,
      crypto.randomUUID(),
    );
    const fresh = initialValues(moved);
    setBody(moved);
    setInitial(fresh);
    setValues({ ...fresh });
    setRebase(null);
    setNotice(t("rebase.done"));
    onChanged();
  }

  const skippedText = (reason: string | null | undefined) =>
    reason && t.has(`skipped.${reason}`)
      ? t(`skipped.${reason}`)
      : t("skipped.other");

  /** Publishing asks first whether the version would go out at all. */
  async function askPublish() {
    try {
      const planned = await previewPublishLocaleBody(page.id, locale);
      // A preview publishes nothing, so `published` is never true here: what
      // says "it would not go out" is the reason it would be skipped for.
      setDecision(
        planned.skipped
          ? { kind: "blocked", reason: skippedText(planned.skipped) }
          : { kind: "publish" },
      );
    } catch (error) {
      decisionFailed(error);
    }
  }

  function decisionFailed(error: unknown) {
    const problem = problemOf(error);
    if (problem?.status === 403) setNotice(t("decision.forbidden"));
    else if (problem?.code === "site_publication_not_ready") {
      setDecision({ kind: "blocked", reason: skippedText(problem.code) });
    } else if (problem?.status === 409) {
      setNotice(t("decision.changed"));
      void load();
    } else setNotice(t("decision.failed"));
  }

  async function confirmDecision() {
    if (!body || !decision || decision.kind === "blocked") return;
    const key = crypto.randomUUID();
    setDeciding(true);
    try {
      let outcome: LanguageDecision;
      if (decision.kind === "accept") {
        outcome = await acceptLocaleBody(
          page.id,
          locale,
          body.body_version,
          key,
        );
        setNotice(
          outcome.published
            ? t("decision.accepted")
            : t("decision.acceptedNotPublished", {
                reason: skippedText(outcome.skipped),
              }),
        );
      } else if (decision.kind === "reject") {
        await rejectLocaleBody(page.id, locale, body.body_version, key);
        setNotice(t("decision.rejected"));
      } else if (decision.kind === "publish") {
        outcome = await publishLocaleBody(page.id, locale, key);
        setNotice(
          outcome.published
            ? t("decision.published", { language: languageName })
            : skippedText(outcome.skipped),
        );
      } else {
        await withdrawLocaleBody(page.id, locale, key);
        setNotice(t("decision.withdrawn", { language: languageName }));
      }
      setDecision(null);
      await load();
      onChanged();
    } catch (error) {
      setDecision(null);
      decisionFailed(error);
    } finally {
      setDeciding(false);
    }
  }

  // A version waits for a decision: the fields carry its text to read, and
  // it is accepted or rejected before anything is written — or ordered again.
  const waiting = body?.pending?.in_units === true;
  // Beside a version of the language's own, the fragments the decision
  // changes: their waiting text is not what the language says now.
  const changedKeys = useMemo(
    () =>
      new Set(
        body?.pending?.in_units && body.version !== null
          ? body.units
              .filter(
                (unit) =>
                  editable(unit) && unit.text !== (unit.current_text ?? null),
              )
              .map((unit) => unit.key)
          : [],
      ),
    [body],
  );
  const filtered = onlyChanged && changedKeys.size > 0;
  // The title and description the waiting version carries: read beside what
  // the language has now, like its fragments.
  const waitingMetadata = waiting ? (body?.pending?.metadata ?? []) : [];
  const changedMetadata = waitingMetadata.filter(
    (item) => item.text !== item.current_text,
  ).length;

  const sections = useMemo(() => {
    const groups = new Map<number, LocaleBodyUnit[]>();
    for (const unit of body?.units ?? []) {
      if (filtered && !changedKeys.has(unit.key)) continue;
      const position = Number(unit.key.split("/", 1)[0]);
      groups.set(position, [...(groups.get(position) ?? []), unit]);
    }
    // In the order the section's own form shows its fields (the heading
    // before the text), not the order the data happens to be stored in.
    return [...groups.entries()].map(
      ([position, units]) =>
        [
          position,
          [...units].sort(
            (left, right) =>
              fieldOrder(body?.block_types[position], left.key) -
              fieldOrder(body?.block_types[position], right.key),
          ),
        ] as const,
    );
  }, [body, changedKeys, filtered]);

  const untouched =
    body !== undefined &&
    body.version === null &&
    !waiting &&
    body.units.every((unit) => unit.text === null);

  // The source editor's one row (UX-039): the way back and the page on the
  // left, then the picker, „Więcej”, preview and save on the right. In the
  // middle, where the source has its device switch, a wide screen says where
  // the structure is changed; narrower, that way is under „Więcej”.
  const toolbar = (
    <div className="studio-toolbar studio-topbar">
      {leading}
      <div className="studio-topbar-page">
        <p className="truncate text-sm font-semibold">{page.name}</p>
        <p className="truncate text-xs text-muted-foreground">
          {languageName}
          {body?.version != null &&
            ` · ${t("versionNamed", { number: body.version })}`}
        </p>
      </div>
      <span
        aria-hidden="true"
        className="studio-topbar-divider hidden xl:block"
      />
      {/* The sentence gives way before the link does. */}
      <p className="studio-topbar-center hidden items-baseline gap-1.5 text-sm text-muted-foreground xl:flex">
        <span className="truncate">{t("structureHint")}</span>
        <button
          type="button"
          className="shrink-0 underline underline-offset-4"
          onClick={onSwitchToSource}
        >
          {t("toSource", { language: sourceName })}
        </button>
      </p>
      <div className="studio-save-actions">
        {languageSwitch}
        <DropdownMenu>
          <DropdownMenuTrigger
            aria-label={studio("more")}
            title={studio("more")}
            className={buttonVariants({
              variant: "outline",
              size: "icon-sm",
              className: "pointer-fine:size-8",
            })}
          >
            <EllipsisIcon aria-hidden="true" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => setMetadataOpen(true)}>
              <Settings2Icon aria-hidden="true" />
              {t("settings")}
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={state !== "ready"}
              onClick={() => void openHistory()}
            >
              <HistoryIcon aria-hidden="true" />
              {t("history")}
            </DropdownMenuItem>
            {body?.live_version_id && !body.withdrawn && (
              <DropdownMenuItem
                onClick={() => setDecision({ kind: "withdraw" })}
              >
                {t("actions.withdraw")}
              </DropdownMenuItem>
            )}
            <DropdownMenuItem className="xl:hidden" onClick={onSwitchToSource}>
              {t("toSource", { language: sourceName })}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="pointer-fine:h-8"
          aria-label={t("preview")}
          title={t("preview")}
          disabled={!body?.version_id && !waiting}
          onClick={() => void openPreview()}
        >
          <EyeIcon aria-hidden="true" />
          <span className="max-sm:hidden">{t("preview")}</span>
        </Button>
        <Button
          type="button"
          size="sm"
          className="pointer-fine:h-8"
          aria-label={t("save")}
          disabled={state !== "ready" || saving || dirtyKeys.length === 0}
          onClick={() => void save()}
        >
          <SaveIcon aria-hidden="true" />
          {/* A phone's one row has room for the short word. */}
          <span className="sm:hidden">{common("save")}</span>
          <span className="max-sm:hidden">{t("save")}</span>
        </Button>
      </div>
    </div>
  );

  function openTranslate() {
    // An order that ended is history: the dialog quotes anew.
    if (jobDone) setJobId(undefined);
    setTranslating(true);
  }

  /** "Przetłumacz", only where the engine takes orders — never a button
   *  that leads nowhere. */
  function translateAction(label: string): ReactNode {
    if (offer.state !== "available") return null;
    return (
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={dirtyKeys.length > 0 || (jobId !== undefined && !jobDone)}
        title={dirtyKeys.length > 0 ? t("banner.saveFirst") : undefined}
        onClick={openTranslate}
      >
        {label}
      </Button>
    );
  }

  function banner() {
    if (!body) return null;
    if (jobId !== undefined && !jobDone) {
      return (
        <div className="border-b bg-muted/40 px-4 py-2 text-sm" role="status">
          {t("actions.translating")}
        </div>
      );
    }
    const lines: {
      tone: "info" | "warning" | "success";
      text: string;
      action?: ReactNode;
    }[] = [];
    const act = (kind: "accept" | "reject" | "publish", label: string) => (
      <Button
        key={kind}
        type="button"
        size="sm"
        variant={kind === "reject" ? "ghost" : "outline"}
        disabled={deciding || dirtyKeys.length > 0}
        title={dirtyKeys.length > 0 ? t("banner.saveFirst") : undefined}
        onClick={() =>
          kind === "publish" ? void askPublish() : setDecision({ kind })
        }
      >
        {label}
      </Button>
    );
    if (body.pending) {
      const reason = body.pending.reason || "other";
      const compared = waiting && body.version !== null;
      lines.push({
        tone: "warning",
        text: t(
          compared
            ? "banner.pendingCompared"
            : waiting
              ? "banner.pendingShown"
              : "banner.pending",
          {
            reason: t.has(`banner.reasons.${reason}`)
              ? t(`banner.reasons.${reason}`)
              : t("banner.reasons.other"),
            count: changedKeys.size + changedMetadata,
          },
        ),
        action: (
          <>
            {act("accept", t("actions.accept"))}
            {act("reject", t("actions.reject"))}
            {/* A long page with two changed fragments: only those. */}
            {changedKeys.size > 0 &&
              changedKeys.size < body.units.filter(editable).length && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  aria-pressed={filtered}
                  onClick={() => setOnlyChanged(!filtered)}
                >
                  {t(filtered ? "banner.showAll" : "banner.onlyChanged")}
                </Button>
              )}
          </>
        ),
      });
    }
    if (body.withdrawn) {
      lines.push({
        tone: "warning",
        text: t("banner.withdrawn"),
        action: act("publish", t("actions.publish")),
      });
    }
    // What waits is decided first: moving it onto the new source or ordering
    // the page again would only add to what waits.
    if (body.outdated && !waiting) {
      lines.push({
        tone: "warning",
        text: t("banner.outdated"),
        action: (
          <>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => void askRebase()}
            >
              {t("rebase.action")}
            </Button>
            {translateAction(t("actions.translateMissing"))}
          </>
        ),
      });
    }
    if (lines.length === 0) {
      if (body.untranslated > 0) {
        lines.push({
          tone: "info",
          text: t("banner.untranslated", { count: body.untranslated }),
          action: translateAction(t("actions.translateMissing")),
        });
      } else if (body.version_id && body.version_id === body.live_version_id) {
        lines.push({ tone: "success", text: t("banner.live") });
      } else if (body.version_id) {
        // Complete, and what visitors read is an older version or none.
        lines.push({
          tone: "info",
          text: t(
            body.live_version_id ? "banner.unpublished" : "banner.notOnSite",
          ),
          action: act("publish", t("actions.publish")),
        });
      } else {
        lines.push({ tone: "success", text: t("banner.complete") });
      }
    }
    const first = lines[0]!;
    return (
      <div
        className="flex flex-wrap items-center gap-3 border-b bg-muted/40 px-4 py-2 text-sm"
        data-tone={first.tone}
      >
        {lines.map((line) => (
          <span key={line.text} className="flex flex-wrap items-center gap-2">
            {line.text}
            {/* The line's actions stay together: under a long sentence they
                wrap as one row, not accept here and reject below. */}
            {line.action && (
              <span className="flex flex-wrap items-center gap-2">
                {line.action}
              </span>
            )}
          </span>
        ))}
      </div>
    );
  }

  function statusOf(unit: LocaleBodyUnit): string {
    if (values[unit.key] !== initial[unit.key]) return t("unit.status.dirty");
    if (unit.text === null) return t("unit.status.missing");
    return t.has(`unit.status.${unit.origin}`)
      ? t(`unit.status.${unit.origin}`)
      : t("unit.status.human");
  }

  function labelOf(
    unit: LocaleBodyUnit,
    blockType: string | undefined,
    order: number,
  ) {
    const keys = labelKeys(blockType, unit.key.split("/").slice(1));
    if (!keys) return t("fragment", { number: order });
    const own = sites.has(keys.labelKey) ? sites(keys.labelKey) : keys.labelKey;
    const base = keys.parentKey
      ? `${sites.has(keys.parentKey) ? sites(keys.parentKey) : keys.parentKey} ${keys.index}: ${own}`
      : own;
    return keys.fragment
      ? `${base} — ${t("fragment", { number: keys.fragment })}`
      : base;
  }

  const sectionTypeName = useSectionTypeName();
  function sectionName(blockType: string | undefined): string {
    return blockType ? sectionTypeName(blockType) : "";
  }

  function row(
    unit: LocaleBodyUnit,
    blockType: string | undefined,
    order: number,
  ) {
    const id = `language-${locale}-${unit.key.replaceAll("/", "-")}`;
    const label = labelOf(unit, blockType, order);
    const error = errors[unit.key];
    const value = values[unit.key] ?? "";
    const present = unit.current_text ?? null;
    const setValue = (next: string) =>
      setValues((current) => ({ ...current, [unit.key]: next }));
    const source =
      unit.kind === "inline" ? (
        <TokenText text={unit.source_text} marks={marks[unit.key] ?? []} />
      ) : (
        unit.source_text
      );
    let field: ReactNode;
    if (unit.kind === "name" || unit.kind === "address") {
      field = (
        <p className="text-sm text-muted-foreground">{t("unit.copied")}</p>
      );
    } else if (unit.placeholder) {
      field = (
        <p className="text-sm text-muted-foreground">{t("unit.placeholder")}</p>
      );
    } else if (unit.kind === "inline") {
      field = (
        <TokenTextField
          id={id}
          value={value}
          onChange={setValue}
          source={unit.source_text}
          marks={marks[unit.key] ?? []}
          labelledBy={`${id}-label`}
          describedBy={error ? `${id}-error` : undefined}
          disabled={saving || waiting}
          onRefused={setNotice}
        />
      );
    } else if (
      unit.source_text.length > 90 ||
      unit.source_text.includes("\n")
    ) {
      field = (
        <Textarea
          id={id}
          aria-labelledby={`${id}-label`}
          aria-invalid={Boolean(error)}
          value={value}
          maxLength={unit.max_length ?? undefined}
          disabled={saving}
          readOnly={waiting}
          onChange={(event) => setValue(event.target.value)}
        />
      );
    } else {
      field = (
        <Input
          id={id}
          aria-labelledby={`${id}-label`}
          aria-invalid={Boolean(error)}
          value={value}
          maxLength={unit.max_length ?? undefined}
          disabled={saving}
          readOnly={waiting}
          onChange={(event) => setValue(event.target.value)}
        />
      );
    }
    return (
      <Field
        key={unit.key}
        data-invalid={Boolean(error)}
        className="grid gap-3 border-b py-4 last:border-b-0 lg:grid-cols-2"
      >
        <div className="min-w-0 space-y-1">
          <span id={`${id}-label`} className="text-sm font-medium">
            {label}
          </span>
          <p
            className="text-sm text-muted-foreground"
            aria-label={t("unit.source")}
          >
            {source}
          </p>
        </div>
        <div className="min-w-0 space-y-2">
          {field}
          <div className="flex flex-wrap items-center gap-2">
            {changedKeys.has(unit.key) && (
              <Badge variant="warning">
                {t(present === null ? "unit.added" : "unit.changed")}
              </Badge>
            )}
            {editable(unit) && (
              <Badge variant="neutral">{statusOf(unit)}</Badge>
            )}
            {editable(unit) &&
              !waiting &&
              (unit.text === null || unit.origin === "copy") && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={saving}
                  onClick={() => setValue(unit.source_text)}
                >
                  {t("unit.keep")}
                </Button>
              )}
            {unit.suggestion && !waiting && (
              <span className="text-sm text-muted-foreground">
                {t("unit.suggestion", { text: unit.suggestion })}{" "}
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => setValue(unit.suggestion ?? "")}
                >
                  {t("unit.useSuggestion")}
                </Button>
              </span>
            )}
          </div>
          {/* What the decision replaces, to read beside what waits. */}
          {changedKeys.has(unit.key) && present !== null && (
            <p className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
              <span className="font-medium text-foreground">
                {t("unit.present")}
              </span>{" "}
              {unit.kind === "inline" ? (
                <TokenText text={present} marks={marks[unit.key] ?? []} />
              ) : (
                present
              )}
            </p>
          )}
          {error && (
            <FieldError id={`${id}-error`}>
              {t.has(`unitErrors.${error}`)
                ? t(`unitErrors.${error}`)
                : t("unitErrors.other")}
            </FieldError>
          )}
        </div>
      </Field>
    );
  }

  let content: ReactNode;
  if (state === "loading") {
    content = (
      <p className="p-6 text-sm text-muted-foreground">{t("loading")}</p>
    );
  } else if (state === "no-address") {
    content = (
      <Card className="m-6">
        <CardHeader>
          <CardTitle>{t("noAddress.title")}</CardTitle>
          <CardDescription>
            {t("noAddress.text", { language: languageName })}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button type="button" onClick={() => setMetadataOpen(true)}>
            {t("noAddress.action")}
          </Button>
        </CardContent>
      </Card>
    );
  } else if (state === "not-enabled") {
    content = <p className="p-6 text-sm">{t("notEnabled")}</p>;
  } else if (state === "error" || !body) {
    content = (
      <div className="space-y-3 p-6">
        <p className="text-sm" role="alert">
          {t("loadError")}
        </p>
        <Button type="button" variant="outline" onClick={() => void load()}>
          {t("retry")}
        </Button>
      </div>
    );
  } else if (untouched && !started) {
    content = (
      <Card className="m-6">
        <CardHeader>
          <CardTitle>{t("empty.title", { language: languageName })}</CardTitle>
          <CardDescription>{t("empty.text")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {offer.state === "available" && (
              <Button type="button" onClick={openTranslate}>
                {t("actions.translate")}
              </Button>
            )}
            <Button
              type="button"
              variant={offer.state === "available" ? "outline" : "default"}
              onClick={() => setStarted(true)}
            >
              {t("empty.manual")}
            </Button>
          </div>
          {/* The engine is there but takes no orders now: said plainly, with
              the manual way whole. Without an engine nothing is said. */}
          {offer.state === "unavailable" && (
            <TranslationUnavailable reasons={offer.reasons} />
          )}
        </CardContent>
      </Card>
    );
  } else {
    let order = 0;
    content = (
      <form
        className="space-y-6 p-4 sm:p-6"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        {waitingMetadata.length > 0 && (
          <section aria-labelledby="language-waiting-metadata">
            <h3
              id="language-waiting-metadata"
              className="text-base font-semibold"
            >
              {t("waitingMetadata.title")}
            </h3>
            <p className="text-sm text-muted-foreground">
              {t("waitingMetadata.hint")}
            </p>
            <FieldGroup className="gap-0">
              {waitingMetadata.map((item) => {
                const id = `language-${locale}-meta-${item.field}`;
                const changed = item.text !== item.current_text;
                const Control = item.field === "description" ? Textarea : Input;
                return (
                  <Field
                    key={item.field}
                    className="grid gap-3 border-b py-4 last:border-b-0 lg:grid-cols-2"
                  >
                    <div className="min-w-0 space-y-1">
                      <span id={`${id}-label`} className="text-sm font-medium">
                        {t(`waitingMetadata.field.${item.field}`)}
                      </span>
                      <p
                        className="text-sm text-muted-foreground"
                        aria-label={t("unit.source")}
                      >
                        {item.source_text}
                      </p>
                    </div>
                    <div className="min-w-0 space-y-2">
                      <Control
                        id={id}
                        aria-labelledby={`${id}-label`}
                        value={item.text}
                        readOnly
                      />
                      {changed && (
                        <Badge variant="warning">
                          {t(
                            item.current_text === null
                              ? "unit.added"
                              : "unit.changed",
                          )}
                        </Badge>
                      )}
                      {changed && item.current_text !== null && (
                        <p className="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
                          <span className="font-medium text-foreground">
                            {t("unit.present")}
                          </span>{" "}
                          {item.current_text}
                        </p>
                      )}
                    </div>
                  </Field>
                );
              })}
            </FieldGroup>
          </section>
        )}
        {sections.map(([position, units]) => {
          const blockType = body.block_types[position];
          return (
            <section
              key={position}
              aria-labelledby={`language-section-${position}`}
            >
              <h3
                id={`language-section-${position}`}
                className="text-base font-semibold"
              >
                {t("section", {
                  number: position + 1,
                  name: sectionName(blockType),
                })}
              </h3>
              <FieldGroup className="gap-0">
                {units.map((unit) => {
                  order += 1;
                  return row(unit, blockType, order);
                })}
              </FieldGroup>
            </section>
          );
        })}
      </form>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {toolbar}
      {state === "ready" && banner()}
      {/* One region for what happened: saved, a conflict, a refused edit. */}
      <p
        role="status"
        aria-live="polite"
        className={notice ? "border-b px-4 py-2 text-sm" : "sr-only"}
      >
        {notice}
      </p>
      <div className="min-h-0 flex-1 overflow-y-auto">{content}</div>

      <LanguageMetadataDialog
        open={metadataOpen}
        onOpenChange={setMetadataOpen}
        page={page}
        locale={locale}
        languageName={languageName}
        onSaved={() => {
          setMetadataOpen(false);
          onChanged();
          void load();
        }}
      />

      <Dialog
        open={preview !== null}
        onOpenChange={(next) => !next && setPreview(null)}
      >
        <DialogContent
          closeLabel={common("close")}
          className="max-h-[90dvh] overflow-y-auto sm:max-w-5xl"
        >
          <DialogTitle>
            {t("previewTitle", { language: languageName })}
          </DialogTitle>
          <DialogDescription>
            {shownPreview &&
              t(shownPreview.waiting ? "versionWaiting" : "versionNamed", {
                number: shownPreview.number,
              })}
          </DialogDescription>
          {shownPreview && (
            <div lang={locale} data-testid="language-preview">
              {renderDraftPreview(
                {
                  kind: "draft-preview",
                  versionId: `${page.id}-${locale}-${shownPreview.number}`,
                  appearance,
                  pagePresentation: null,
                  blocks: (
                    shownPreview.blocks as Parameters<typeof toSiteBlock>[0][]
                  ).map(toSiteBlock),
                  designTokens,
                },
                registry,
                privateMediaRenderer(
                  new Set<string>(),
                  interfaceLocale === "en" ? "en" : "pl",
                ),
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
        <DialogContent closeLabel={common("close")} className="sm:max-w-lg">
          <DialogTitle>
            {t("historyTitle", { language: languageName })}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t("history")}
          </DialogDescription>
          {versions && versions.length === 0 && (
            <p className="text-sm text-muted-foreground">{t("historyEmpty")}</p>
          )}
          {/* What waits is decided first: accepting it would lay it over
              a version restored now. */}
          {waiting && (
            <p className="text-sm text-muted-foreground">
              {t("historyWaiting")}
            </p>
          )}
          <ul className="divide-y">
            {(versions ?? []).map((version) => (
              <li
                key={version.id}
                className="flex flex-wrap items-center justify-between gap-2 py-2"
              >
                <span className="text-sm">
                  <span className="font-medium">
                    {t("versionNamed", { number: version.number })}
                  </span>{" "}
                  <span className="text-muted-foreground">
                    {t.has(`versionOrigin.${version.origin}`)
                      ? t(`versionOrigin.${version.origin}`)
                      : t("versionOrigin.unknown")}
                    {" · "}
                    {new Date(version.created_at).toLocaleString(
                      interfaceLocale,
                    )}
                  </span>{" "}
                  {version.id === body?.pending?.version_id && (
                    <Badge variant="warning">{t("historyWaitingMark")}</Badge>
                  )}
                </span>
                {version.number !== body?.version && !waiting && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      setRestoring({ id: version.id, number: version.number })
                    }
                  >
                    {t("restore")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </DialogContent>
      </Dialog>

      <Dialog
        open={restoring !== null}
        onOpenChange={(next) => !next && setRestoring(null)}
      >
        <DialogContent closeLabel={common("close")}>
          <DialogTitle>
            {t("restoreTitle", { number: shownRestoring?.number ?? 0 })}
          </DialogTitle>
          <DialogDescription>
            {t("restoreText", { number: shownRestoring?.number ?? 0 })}
          </DialogDescription>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setRestoring(null)}
            >
              {common("cancel")}
            </Button>
            <Button type="button" onClick={() => void confirmRestore()}>
              {t("restore")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {offer.state === "available" && (
        <TranslateDialog
          open={translating}
          onOpenChange={setTranslating}
          targets={[
            {
              source_key: "sites.page",
              object_id: page.id,
              locale,
              basis: "published",
            },
          ]}
          languageName={() => languageName}
          reasonText={(reason) =>
            t.has(`banner.reasons.${reason}`)
              ? t(`banner.reasons.${reason}`)
              : t("banner.reasons.other")
          }
          allowWorking
          offer={offer.offer}
          job={job}
          onOrdered={(started) => setJobId(started.id)}
        />
      )}

      <Dialog
        open={decision !== null}
        onOpenChange={(next) => !next && !deciding && setDecision(null)}
      >
        <DialogContent closeLabel={common("close")}>
          {shownDecision?.kind === "blocked" ? (
            <>
              <DialogTitle>{t("decision.publishBlockedTitle")}</DialogTitle>
              <DialogDescription>
                {shownDecision.reason.charAt(0).toUpperCase() +
                  shownDecision.reason.slice(1)}
                .
              </DialogDescription>
              <div className="flex justify-end">
                <Button type="button" onClick={() => setDecision(null)}>
                  {t("decision.close")}
                </Button>
              </div>
            </>
          ) : shownDecision ? (
            <>
              <DialogTitle>
                {t(`decision.${shownDecision.kind}Title`, {
                  language: languageName,
                })}
              </DialogTitle>
              <DialogDescription>
                {t(`decision.${shownDecision.kind}Text`, {
                  language: languageName,
                })}
              </DialogDescription>
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={deciding}
                  onClick={() => setDecision(null)}
                >
                  {common("cancel")}
                </Button>
                <Button
                  type="button"
                  variant={
                    shownDecision.kind === "reject" ||
                    shownDecision.kind === "withdraw"
                      ? "destructive"
                      : "default"
                  }
                  disabled={deciding || decision === null}
                  onClick={() => void confirmDecision()}
                >
                  {t(`actions.${shownDecision.kind}`)}
                </Button>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog
        open={rebase !== null}
        onOpenChange={(next) => !next && setRebase(null)}
      >
        <DialogContent closeLabel={common("close")}>
          <DialogTitle>{t("rebase.title")}</DialogTitle>
          <DialogDescription>
            {t("rebase.text", { count: shownRebase?.untranslated ?? 0 })}
          </DialogDescription>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setRebase(null)}
            >
              {common("cancel")}
            </Button>
            <Button type="button" onClick={() => void confirmRebase()}>
              {t("rebase.confirm")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** This language's address, title and descriptions (the page's metadata in
 *  `locale`); a new version gets its address from its title. */
function LanguageMetadataDialog({
  open,
  onOpenChange,
  page,
  locale,
  languageName,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  page: PageSummary;
  locale: string;
  languageName: string;
  onSaved: () => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const [current, setCurrent] = useState<PageTranslation | null>(null);
  const [values, setValues] = useState({
    slug: "",
    title: "",
    description: "",
    social_title: "",
    social_description: "",
  });
  const [slugTouched, setSlugTouched] = useState(false);
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);
  // The fields open once this language's metadata has arrived: it fills the
  // form, and words typed before that were overwritten.
  const [loaded, setLoaded] = useState(false);
  const receipt = useRef<MutationReceipt | undefined>(undefined);

  useEffect(() => {
    if (!open) return;
    let active = true;
    void listPageTranslations(page.id)
      .then((list) => {
        if (!active) return;
        const found = list.items.find((item) => item.locale === locale) ?? null;
        setCurrent(found);
        setSlugTouched(Boolean(found));
        setValues({
          slug: found?.slug ?? "",
          title: found?.title ?? "",
          description: found?.description ?? "",
          social_title: found?.social_title ?? "",
          social_description: found?.social_description ?? "",
        });
        setProblem("");
        setLoaded(true);
      })
      .catch(() => {
        if (active) setProblem(t("languageMode.loadError"));
      });
    return () => {
      active = false;
      // The next opening reads the metadata again.
      setLoaded(false);
    };
  }, [open, page.id, locale, t]);

  const set = (name: keyof typeof values) => (next: string) =>
    setValues((previous) => ({
      ...previous,
      [name]: next,
      ...(name === "title" && !slugTouched && !current?.slug_locked
        ? { slug: slugFromTitle(next) }
        : {}),
    }));

  async function submit() {
    const input = {
      ...values,
      expected_version: current?.version ?? 0,
      allow_title_fallback: false,
      allow_description_fallback: false,
      allow_social_title_fallback: false,
      allow_social_description_fallback: false,
    };
    setBusy(true);
    setProblem("");
    try {
      await savePageTranslation(
        page.id,
        locale,
        input,
        mutationKey(receipt, `translation-${page.id}-${locale}`, input),
      );
      receipt.current = undefined;
      onSaved();
    } catch (error) {
      setProblem(
        problemOf(error)?.code === "translation_version_conflict"
          ? t("translationConflict")
          : error instanceof Error
            ? error.message
            : t("saveMetadata"),
      );
    } finally {
      setBusy(false);
    }
  }

  const fields: [keyof typeof values, string, boolean][] = [
    ["title", t("metaTitle"), false],
    ["slug", t("slug"), false],
    ["description", t("metaDescription"), true],
    ["social_title", t("socialTitle"), false],
    ["social_description", t("socialDescription"), true],
  ];
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        closeLabel={common("close")}
        className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl"
      >
        <DialogTitle>
          {t("languageMode.settings")} — {languageName}
        </DialogTitle>
        <DialogDescription>{t("metadataDescription")}</DialogDescription>
        <form
          className="space-y-5"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <FieldGroup>
            {fields.map(([name, label, multiline]) => {
              const id = `language-meta-${locale}-${name}`;
              return (
                <Field key={name}>
                  <FieldLabel htmlFor={id}>{label}</FieldLabel>
                  {multiline ? (
                    <Textarea
                      id={id}
                      value={values[name]}
                      disabled={!loaded}
                      onChange={(event) => set(name)(event.target.value)}
                    />
                  ) : (
                    <Input
                      id={id}
                      value={values[name]}
                      disabled={
                        !loaded ||
                        (name === "slug" && Boolean(current?.slug_locked))
                      }
                      onChange={(event) => {
                        if (name === "slug") setSlugTouched(true);
                        set(name)(event.target.value);
                      }}
                    />
                  )}
                  {name === "slug" && current?.slug_locked && (
                    <FieldDescription>{t("slugLocked")}</FieldDescription>
                  )}
                </Field>
              );
            })}
          </FieldGroup>
          {problem && (
            <p role="alert" className="text-sm text-destructive">
              {problem}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              {common("cancel")}
            </Button>
            <Button
              type="submit"
              disabled={busy || !loaded || !values.slug || !values.title}
            >
              {t("saveMetadata")}
            </Button>
          </div>
        </form>
        {/* What a search engine reads of this version after the next
            publication (TL18); a version without an address has nothing. */}
        {current && (
          <SeoPreview
            locale={locale}
            pageId={page.id}
            siteId={page.site_id}
            version={current.version}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
