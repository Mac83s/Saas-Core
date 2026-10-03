"use client";

import { useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  ArchiveIcon,
  BookmarkPlusIcon,
  PencilIcon,
  PlusIcon,
} from "lucide-react";
import {
  archiveSiteTemplate,
  createSiteTemplate,
  listSiteTemplates,
  saveSiteTemplateVersion,
  updateSiteTemplate,
  type SiteTemplate,
} from "@saas-core/api-client";
import type { BlockImageRenderer } from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Textarea } from "@saas-core/ui/components/textarea";

import {
  blockPayload,
  editableBlocks,
  mediaIdsInBlocks,
  registry,
  toSiteBlock,
  type BlockFormValues,
} from "./block-form";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { PageEditorContext } from "./page-editor-context";
import { sitesErrorMessage } from "./problem";

const CHANGED = "sites:own-templates-changed";

/** Every open list (the library rail, a dialog, the page gallery) reads the
 *  templates again after one of them saves, renames or archives. */
function announceChange() {
  window.dispatchEvent(new Event(CHANGED));
}

/** The organization's own templates (of one kind, or all), and the plan's
 *  limit — one number for sections and pages together. */
export function useOwnTemplates(kind?: "section" | "page") {
  const [items, setItems] = useState<SiteTemplate[]>([]);
  const [limit, setLimit] = useState<number | null>(null);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let live = true;
    const load = () =>
      void listSiteTemplates(kind)
        .then((list) => {
          if (!live) return;
          setItems(list.items);
          setLimit(list.limit);
        })
        // The library works without own templates; the next change retries.
        .catch(() => {
          if (live) setItems([]);
        })
        .finally(() => {
          if (live) setLoaded(true);
        });
    load();
    window.addEventListener(CHANGED, load);
    return () => {
      live = false;
      window.removeEventListener(CHANGED, load);
    };
  }, [kind]);
  return { items, limit, loaded };
}

/** A photo's place in a miniature, as in the layout comparison. */
const photoPlaceholder: BlockImageRenderer = (image) => (
  <span className="studio-layout-photo" role="img" aria-label={image.alt} />
);

/** An own template drawn from its newest version, in the page's look. */
export function OwnTemplateMiniature({
  template,
  row = false,
}: {
  template: SiteTemplate;
  /** The section library's compact row: a small picture of a wide page. */
  row?: boolean;
}) {
  const look = useContext(PageEditorContext)?.look ?? "site-theme";
  let blocks: ReactNode = null;
  try {
    blocks = template.version.blocks.map((block, index) =>
      registry.render(
        toSiteBlock(block),
        `${template.id}-${index}`,
        undefined,
        photoPlaceholder,
      ),
    );
  } catch {
    blocks = null;
  }
  if (row)
    return (
      <div className="studio-library-thumb" aria-hidden="true" inert>
        <div className={`${look} studio-library-thumb__canvas`}>{blocks}</div>
      </div>
    );
  return (
    <div className="relative aspect-video overflow-hidden bg-muted">
      <div
        className="pointer-events-none absolute inset-0 overflow-hidden"
        aria-hidden="true"
        inert
      >
        <div
          className={`${look} w-[300%] origin-top-left scale-[0.3333333333]`}
        >
          {blocks}
        </div>
      </div>
    </div>
  );
}

/** "Zapisz jako szablon": a new template of the organization, or the next
 *  version of one it has (owner's answers 1a–3a: sections and pages, with
 *  their content and photos, for everyone in the organization). */
export function SaveAsTemplate({
  kind,
  blocks,
  pagePresentation,
  sourcePageId,
  triggerLabel,
  disabled,
}: {
  kind: "section" | "page";
  blocks: () => BlockFormValues[];
  pagePresentation?: () => unknown;
  sourcePageId?: string;
  triggerLabel: string;
  disabled?: boolean;
}) {
  const t = useTranslations("Sites.ownTemplates");
  const common = useTranslations("Common");
  const sites = useTranslations("Sites");
  const templates = useOwnTemplates();
  const sameKind = templates.items.filter((item) => item.kind === kind);
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [saved, setSaved] = useState<string>();
  const receipt = useRef<MutationReceipt | undefined>(undefined);
  const full =
    templates.limit !== null && templates.items.length >= templates.limit;
  async function save() {
    const current = blocks();
    const content = {
      blocks: current.map(blockPayload),
      page_presentation:
        kind === "page" ? (pagePresentation?.() ?? null) : null,
      media_asset_ids: mediaIdsInBlocks(current),
      source_page_id: sourcePageId ?? null,
    };
    setBusy(true);
    setProblem(undefined);
    try {
      const existing = sameKind.find((item) => item.id === target);
      const result = existing
        ? await saveSiteTemplateVersion(
            existing.id,
            { ...content, expected_version: existing.version.number },
            mutationKey(receipt, `template-${existing.id}`, content),
          )
        : await createSiteTemplate(
            { ...content, kind, name, description },
            mutationKey(receipt, `template-${kind}`, {
              ...content,
              name,
              description,
            }),
          );
      receipt.current = undefined;
      setSaved(
        existing
          ? t("savedVersion", {
              name: result.name,
              number: result.version.number,
            })
          : t("saved", { name: result.name }),
      );
      setName("");
      setDescription("");
      setTarget("");
      announceChange();
    } catch (error) {
      setProblem(sitesErrorMessage(error, sites));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (busy) return;
        setOpen(next);
        if (next) {
          setSaved(undefined);
          setProblem(undefined);
        }
      }}
    >
      <DialogTrigger
        render={
          <Button
            type="button"
            variant="outline"
            // Long labels wrap in the 300 px rail instead of scrolling it.
            className="h-auto min-h-10 w-full whitespace-normal py-2"
            disabled={disabled}
          />
        }
      >
        <BookmarkPlusIcon aria-hidden="true" />
        {triggerLabel}
      </DialogTrigger>
      <DialogContent closeLabel={common("close")} className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {kind === "page" ? t("savePageTitle") : t("saveSectionTitle")}
          </DialogTitle>
          <DialogDescription>{t("saveDescription")}</DialogDescription>
        </DialogHeader>
        {saved ? (
          <p role="status" className="rounded-lg bg-muted px-3 py-2 text-sm">
            {saved}
          </p>
        ) : null}
        {problem ? (
          <p role="alert" className="text-sm text-destructive">
            {problem}
          </p>
        ) : null}
        <form
          className="space-y-4"
          onSubmit={(event) => {
            // The dialog sits in the page form's React tree: its submit
            // would otherwise also save the page.
            event.preventDefault();
            event.stopPropagation();
            void save();
          }}
        >
          {sameKind.length > 0 && (
            <Field>
              <FieldLabel htmlFor={`own-template-target-${kind}`}>
                {t("saveAs")}
              </FieldLabel>
              <NativeSelect
                id={`own-template-target-${kind}`}
                value={target}
                onChange={(event) => setTarget(event.target.value)}
              >
                <option value="">{t("newTemplate")}</option>
                {sameKind.map((item) => (
                  <option key={item.id} value={item.id}>
                    {t("newVersionOf", { name: item.name })}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          )}
          {target === "" && (
            <>
              <Field>
                <FieldLabel htmlFor={`own-template-name-${kind}`}>
                  {t("name")}
                </FieldLabel>
                <Input
                  id={`own-template-name-${kind}`}
                  required
                  maxLength={120}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor={`own-template-description-${kind}`}>
                  {t("description")}
                </FieldLabel>
                <Textarea
                  id={`own-template-description-${kind}`}
                  maxLength={500}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </Field>
              {full && (
                <p className="text-sm text-destructive">
                  {t("limitReached", { limit: templates.limit ?? 0 })}
                </p>
              )}
            </>
          )}
          <p className="text-xs text-muted-foreground">
            {target ? t("versionHint") : t("copyHint")}
          </p>
          <div className="flex justify-end gap-2">
            <Button
              type="submit"
              disabled={busy || (target === "" && (!name.trim() || full))}
            >
              {target ? t("saveVersion") : t("save")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Rename and archive, next to a template in the library or the gallery. */
export function OwnTemplateActions({ template }: { template: SiteTemplate }) {
  const t = useTranslations("Sites.ownTemplates");
  const common = useTranslations("Common");
  const sites = useTranslations("Sites");
  const [mode, setMode] = useState<"rename" | "archive" | null>(null);
  const [name, setName] = useState(template.name);
  const [description, setDescription] = useState(template.description);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setProblem(undefined);
    try {
      await action();
      setMode(null);
      announceChange();
    } catch (error) {
      setProblem(sitesErrorMessage(error, sites));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        aria-label={t("renameNamed", { name: template.name })}
        onClick={() => {
          setName(template.name);
          setDescription(template.description);
          setProblem(undefined);
          setMode("rename");
        }}
      >
        <PencilIcon aria-hidden="true" />
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        aria-label={t("archiveNamed", { name: template.name })}
        onClick={() => {
          setProblem(undefined);
          setMode("archive");
        }}
      >
        <ArchiveIcon aria-hidden="true" />
      </Button>
      <Dialog
        open={mode !== null}
        onOpenChange={(next) => {
          if (!next && !busy) setMode(null);
        }}
      >
        <DialogContent closeLabel={common("close")} className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {mode === "archive"
                ? t("archiveTitle", { name: template.name })
                : t("renameTitle")}
            </DialogTitle>
            <DialogDescription>
              {mode === "archive" ? t("archiveDescription") : t("renameHint")}
            </DialogDescription>
          </DialogHeader>
          {problem ? (
            <p role="alert" className="text-sm text-destructive">
              {problem}
            </p>
          ) : null}
          {mode === "rename" && (
            <div className="space-y-4">
              <Field>
                <FieldLabel htmlFor={`rename-${template.id}`}>
                  {t("name")}
                </FieldLabel>
                <Input
                  id={`rename-${template.id}`}
                  maxLength={120}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor={`describe-${template.id}`}>
                  {t("description")}
                </FieldLabel>
                <Textarea
                  id={`describe-${template.id}`}
                  maxLength={500}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </Field>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => setMode(null)}
            >
              {common("cancel")}
            </Button>
            {mode === "archive" ? (
              <Button
                type="button"
                variant="destructive"
                disabled={busy}
                onClick={() => void run(() => archiveSiteTemplate(template.id))}
              >
                {t("archive")}
              </Button>
            ) : (
              <Button
                type="button"
                disabled={busy || !name.trim()}
                onClick={() =>
                  void run(() =>
                    updateSiteTemplate(template.id, { name, description }),
                  )
                }
              >
                {t("saveName")}
              </Button>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** "Szablony firmy" at the top of the section library: a saved section goes
 *  in as a copy, so editing it on this page leaves the template alone. */
export function OwnSectionTemplates({
  query,
  blockType,
  compact,
  disabled,
  onAdd,
}: {
  query: string;
  blockType: string;
  compact: boolean;
  disabled: boolean;
  onAdd: (block: BlockFormValues) => void;
}) {
  const t = useTranslations("Sites.ownTemplates");
  const templates = useOwnTemplates("section");
  const search = query.trim().toLocaleLowerCase();
  const shown = templates.items.filter(
    (template) =>
      (!blockType || template.version.blocks[0]?.block_type === blockType) &&
      (!search ||
        `${template.name} ${template.description}`
          .toLocaleLowerCase()
          .includes(search)),
  );
  if (shown.length === 0) return null;
  if (compact)
    return (
      <section className="space-y-1.5" aria-labelledby="own-section-templates">
        <h4 id="own-section-templates" className="studio-library-group">
          {t("sectionGroup")}
        </h4>
        <ul className="studio-library-list">
          {shown.map((template) => (
            <li
              key={template.id}
              className="studio-library-row studio-library-row--own"
            >
              <OwnTemplateMiniature template={template} row />
              <div className="studio-library-row__text">
                <h5>{template.name}</h5>
                <p>
                  {template.description ||
                    t("versionBy", {
                      number: template.version.number,
                      author:
                        template.version.created_by.name ||
                        template.version.created_by.email,
                    })}
                </p>
              </div>
              <div className="studio-library-row__actions">
                <OwnTemplateActions template={template} />
                <Button
                  type="button"
                  variant="secondary"
                  size="icon-sm"
                  disabled={disabled}
                  aria-label={t("addNamed", { name: template.name })}
                  title={t("add")}
                  onClick={() =>
                    onAdd(
                      editableBlocks(template.version.blocks.slice(0, 1))[0],
                    )
                  }
                >
                  <PlusIcon aria-hidden="true" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </section>
    );
  return (
    <section className="space-y-3" aria-labelledby="own-section-templates">
      <h3 id="own-section-templates" className="text-sm font-semibold">
        {t("sectionGroup")}
      </h3>
      <ul
        className={
          compact ? "grid gap-3" : "grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        }
      >
        {shown.map((template) => (
          <li
            key={template.id}
            className="flex min-w-0 flex-col overflow-hidden rounded-xl border bg-background shadow-xs"
          >
            <OwnTemplateMiniature template={template} />
            <OwnTemplateBody template={template}>
              <Button
                type="button"
                size="sm"
                disabled={disabled}
                aria-label={t("addNamed", { name: template.name })}
                onClick={() =>
                  onAdd(editableBlocks(template.version.blocks.slice(0, 1))[0])
                }
              >
                <PlusIcon aria-hidden="true" />
                {t("add")}
              </Button>
            </OwnTemplateBody>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The organization's page templates beside the ready recipes. */
export function OwnPageTemplates({
  disabled,
  onUse,
  compact = false,
  save,
}: {
  disabled: boolean;
  onUse: (template: SiteTemplate) => void;
  /** The studio's panel: one row per template, "save" beside them. */
  compact?: boolean;
  save?: ReactNode;
}) {
  const t = useTranslations("Sites.ownTemplates");
  const templates = useOwnTemplates("page");
  if (compact)
    return (
      <section className="space-y-2" aria-labelledby="own-page-templates">
        <h4 id="own-page-templates" className="studio-library-group">
          {t("pageGroup")}
        </h4>
        {templates.loaded && templates.items.length === 0 ? (
          <div className="studio-template-empty">
            <p>{t("pageEmpty")}</p>
            {save}
          </div>
        ) : (
          <>
            <ul className="studio-library-list">
              {templates.items.map((template) => (
                <li
                  key={template.id}
                  className="studio-library-row studio-library-row--own"
                >
                  <OwnTemplateMiniature template={template} row />
                  <div className="studio-library-row__text">
                    <h5>{template.name}</h5>
                    <p>
                      {template.description ||
                        t("versionBy", {
                          number: template.version.number,
                          author:
                            template.version.created_by.name ||
                            template.version.created_by.email,
                        })}
                    </p>
                  </div>
                  <div className="studio-library-row__actions">
                    <OwnTemplateActions template={template} />
                    <Button
                      type="button"
                      size="sm"
                      className="studio-row-text-button"
                      disabled={disabled}
                      aria-label={t("useNamed", { name: template.name })}
                      onClick={() => onUse(template)}
                    >
                      {t("use")}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
            {save}
          </>
        )}
      </section>
    );
  return (
    <section className="space-y-3" aria-labelledby="own-page-templates">
      <h3 id="own-page-templates" className="text-sm font-semibold">
        {t("pageGroup")}
      </h3>
      {templates.loaded && templates.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("pageEmpty")}</p>
      ) : (
        <ul className="grid gap-4">
          {templates.items.map((template) => (
            <li
              key={template.id}
              className="flex min-w-0 flex-col overflow-hidden rounded-xl border bg-background shadow-xs"
            >
              <OwnTemplateMiniature template={template} />
              <OwnTemplateBody template={template}>
                <Button
                  type="button"
                  size="sm"
                  disabled={disabled}
                  aria-label={t("useNamed", { name: template.name })}
                  onClick={() => onUse(template)}
                >
                  {t("use")}
                </Button>
              </OwnTemplateBody>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function OwnTemplateBody({
  template,
  children,
}: {
  template: SiteTemplate;
  children: ReactNode;
}) {
  const t = useTranslations("Sites.ownTemplates");
  return (
    <div className="flex flex-1 flex-col gap-2 p-3">
      <h4 className="text-sm leading-snug font-semibold [overflow-wrap:anywhere]">
        {template.name}
      </h4>
      {template.description ? (
        <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground [overflow-wrap:anywhere]">
          {template.description}
        </p>
      ) : null}
      <p className="flex-1 text-xs text-muted-foreground [overflow-wrap:anywhere]">
        {t("versionBy", {
          number: template.version.number,
          author:
            template.version.created_by.name ||
            template.version.created_by.email,
        })}
      </p>
      <div className="flex flex-wrap items-center justify-end gap-1 pt-1">
        <OwnTemplateActions template={template} />
        {children}
      </div>
    </div>
  );
}
