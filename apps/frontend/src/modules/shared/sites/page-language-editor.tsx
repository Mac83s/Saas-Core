"use client";

/** The page editor in another language (TL15). The source decides the
 *  structure — sections, images, links, layout — and this mode edits only
 *  the words: one row per fragment, the source's text beside the field
 *  (two columns from 1024 px, one under the other on a phone). Saving sends
 *  only what changed, against this language's own version; after a conflict
 *  the new version loads and the unsaved words go back on top of it. */

import {
  ApiProblemError,
  getLocaleBody,
  getLocaleBodyVersion,
  listLocaleBodyVersions,
  listPageTranslations,
  previewRebaseLocaleBody,
  rebaseLocaleBody,
  restoreLocaleBodyVersion,
  saveLocaleBody,
  savePageTranslation,
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

import {
  blockOptions,
  registry,
  toSiteBlock,
  useSectionTypeName,
} from "./block-form";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { privateMediaRenderer } from "./private-media-preview";
import { TokenText, TokenTextField } from "./rich-text-token-field";
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

function problemOf(error: unknown): ApiProblemError["problem"] | null {
  return error instanceof ApiProblemError ? error.problem : null;
}

export interface PageLanguageEditorProps {
  readonly page: PageSummary;
  /** The language shown, never the source. */
  readonly locale: string;
  readonly languageName: string;
  readonly sourceName: string;
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
  } | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [versions, setVersions] = useState<LocaleBodyVersionList["items"]>();
  const [restoring, setRestoring] = useState<{
    id: string;
    number: number;
  } | null>(null);
  const [rebase, setRebase] = useState<{ untranslated: number } | null>(null);
  const receipt = useRef<MutationReceipt | undefined>(undefined);

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
      } catch (error) {
        const code = problemOf(error)?.code;
        setState(
          code === "translation_not_found"
            ? "no-address"
            : code === "locale_not_enabled"
              ? "not-enabled"
              : "error",
        );
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
    if (!body?.version_id || body.version === null) return;
    const shown = await getLocaleBodyVersion(page.id, locale, body.version_id);
    setPreview({ number: shown.version.number, blocks: shown.blocks });
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

  const sections = useMemo(() => {
    const groups = new Map<number, LocaleBodyUnit[]>();
    for (const unit of body?.units ?? []) {
      const position = Number(unit.key.split("/", 1)[0]);
      groups.set(position, [...(groups.get(position) ?? []), unit]);
    }
    return [...groups.entries()];
  }, [body]);

  const untouched =
    body !== undefined &&
    body.version === null &&
    body.units.every((unit) => unit.text === null);

  // The editor's toolbar shape (UX-039): the picker, then "Więcej", preview
  // and save on the right; what changes the structure is not here at all.
  const toolbar = (
    <div className="studio-toolbar">
      <p className="text-sm text-muted-foreground max-md:hidden">
        {t("structureHint")}{" "}
        <button
          type="button"
          className="underline underline-offset-4"
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
            className={buttonVariants({
              variant: "ghost",
              className: "max-sm:px-2.5",
            })}
          >
            <EllipsisIcon aria-hidden="true" />
            <span className="max-sm:hidden">{studio("more")}</span>
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
            <DropdownMenuItem className="md:hidden" onClick={onSwitchToSource}>
              {t("toSource", { language: sourceName })}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          type="button"
          variant="outline"
          aria-label={t("preview")}
          title={t("preview")}
          disabled={!body?.version_id}
          onClick={() => void openPreview()}
        >
          <EyeIcon aria-hidden="true" />
          <span className="max-sm:hidden">{t("preview")}</span>
        </Button>
        <Button
          type="button"
          disabled={state !== "ready" || saving || dirtyKeys.length === 0}
          onClick={() => void save()}
        >
          <SaveIcon aria-hidden="true" />
          {t("save")}
        </Button>
      </div>
    </div>
  );

  function banner() {
    if (!body) return null;
    const lines: {
      tone: "info" | "warning" | "success";
      text: string;
      action?: ReactNode;
    }[] = [];
    if (body.pending) {
      const reason = body.pending.reason || "other";
      lines.push({
        tone: "warning",
        text: t("banner.pending", {
          reason: t.has(`banner.reasons.${reason}`)
            ? t(`banner.reasons.${reason}`)
            : t("banner.reasons.other"),
        }),
      });
    }
    if (body.withdrawn)
      lines.push({ tone: "warning", text: t("banner.withdrawn") });
    if (body.outdated) {
      lines.push({
        tone: "warning",
        text: t("banner.outdated"),
        action: (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void askRebase()}
          >
            {t("rebase.action")}
          </Button>
        ),
      });
    }
    if (lines.length === 0) {
      lines.push(
        body.untranslated > 0
          ? {
              tone: "info",
              text: t("banner.untranslated", { count: body.untranslated }),
            }
          : { tone: "success", text: t("banner.complete") },
      );
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
            {line.action}
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
          disabled={saving}
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
            {editable(unit) && (
              <Badge variant="neutral">{statusOf(unit)}</Badge>
            )}
            {editable(unit) &&
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
            {unit.suggestion && (
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
        <CardContent className="flex flex-wrap gap-2">
          <Button type="button" onClick={() => setStarted(true)}>
            {t("empty.manual")}
          </Button>
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
            {t("versionNamed", { number: preview?.number ?? 0 })}
          </DialogDescription>
          {preview && (
            <div lang={locale} data-testid="language-preview">
              {renderDraftPreview(
                {
                  kind: "draft-preview",
                  versionId: `${page.id}-${locale}-${preview.number}`,
                  appearance,
                  pagePresentation: null,
                  blocks: (
                    preview.blocks as Parameters<typeof toSiteBlock>[0][]
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
                  </span>
                </span>
                {version.number !== body?.version && (
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
            {t("restoreTitle", { number: restoring?.number ?? 0 })}
          </DialogTitle>
          <DialogDescription>
            {t("restoreText", { number: restoring?.number ?? 0 })}
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

      <Dialog
        open={rebase !== null}
        onOpenChange={(next) => !next && setRebase(null)}
      >
        <DialogContent closeLabel={common("close")}>
          <DialogTitle>{t("rebase.title")}</DialogTitle>
          <DialogDescription>
            {t("rebase.text", { count: rebase?.untranslated ?? 0 })}
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
  const receipt = useRef<MutationReceipt | undefined>(undefined);

  useEffect(() => {
    if (!open) return;
    let active = true;
    void listPageTranslations(page.id).then((list) => {
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
    });
    return () => {
      active = false;
    };
  }, [open, page.id, locale]);

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
                      onChange={(event) => set(name)(event.target.value)}
                    />
                  ) : (
                    <Input
                      id={id}
                      value={values[name]}
                      disabled={
                        name === "slug" && Boolean(current?.slug_locked)
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
              disabled={busy || !values.slug || !values.title}
            >
              {t("saveMetadata")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
