"use client";

/** The writing panel for structured rich text (`core.rich_text` v2 `content`
 *  and `aside.content`). It edits a node array inside the surrounding RHF form
 *  in place: no nested form, no second copy of the data. Heading text and
 *  anchor are registered, so typing coalesces into one undo step; runs, lists
 *  and optional texts are edited in a local buffer written with `setValue` on
 *  blur and after a pause — parsing runs on every keystroke would fight the
 *  caret and flood the history. */

import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type KeyboardEvent,
} from "react";
import { useTranslations } from "next-intl";
import {
  get,
  useFieldArray,
  useFormContext,
  useFormState,
  useWatch,
} from "react-hook-form";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  BoldIcon,
  ItalicIcon,
  LinkIcon,
  Trash2Icon,
} from "lucide-react";

import {
  isRichTextAnchor,
  richTextAnchorSlug,
  type RichTextNode,
  type RichTextSpan,
} from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Textarea } from "@saas-core/ui/components/textarea";

import { ImageCropUpload } from "../media/crop";
import {
  hasBlankLines,
  isRichTextHref,
  linkMarkup,
  listToText,
  markupToSpans,
  splitParagraph,
  spansToMarkup,
  textToListItems,
} from "./rich-text-markup";
import { htmlToRichNodes, plainTextToRichNodes } from "./rich-text-paste";

type NodeType = RichTextNode["type"];
export type RichTextMediaOption = { id: string; label: string };

const MAX_NODES = 160;
const IDLE_COMMIT_MS = 700;
const ALL_NODES: readonly NodeType[] = [
  "paragraph",
  "heading",
  "list",
  "quote",
  "note",
  "figure",
];
const INSERTIONS = [
  ["paragraph", "paragraph"],
  ["heading2", "heading"],
  ["heading3", "heading"],
  ["heading4", "heading"],
  ["bulletList", "list"],
  ["orderedList", "list"],
  ["quote", "quote"],
  ["note", "note"],
  ["figure", "figure"],
] as const;
type Insertion = (typeof INSERTIONS)[number][0];

/** Every heading and section anchor in `value`, duplicates included: they
 *  share one namespace on the page. */
function collectAnchors(value: unknown, found: string[] = []): string[] {
  if (Array.isArray(value))
    value.forEach((item) => collectAnchors(item, found));
  else if (value !== null && typeof value === "object") {
    const node = value as Record<string, unknown>;
    if (node.type === "heading" && typeof node.anchor === "string")
      found.push(node.anchor);
    const section = node.presentation as { anchor?: unknown } | undefined;
    if (typeof section?.anchor === "string") found.push(section.anchor);
    Object.values(node).forEach((item) => collectAnchors(item, found));
  }
  return found;
}

/** The first message under an RHF error subtree (schema issues land on the
 *  deepest path, e.g. `content.2.content.0.text`). `ref` is a DOM node. */
function firstError(node: unknown): string | undefined {
  if (node === null || typeof node !== "object") return undefined;
  const message = (node as { message?: unknown }).message;
  if (typeof message === "string" && message) return message;
  for (const [key, child] of Object.entries(node)) {
    if (key === "ref") continue;
    const found = firstError(child);
    if (found) return found;
  }
  return undefined;
}

function useErrorText(path: string) {
  const t = useTranslations("Sites");
  const { control } = useFormContext();
  const { errors } = useFormState({ control, name: path });
  /** `deep: false` reads only the error on the path itself. */
  return (subPath: string, deep = true) => {
    const node: unknown = get(errors, subPath ? `${path}.${subPath}` : path);
    const key = deep
      ? firstError(node)
      : ((node as { message?: string } | undefined)?.message ?? undefined);
    return key === undefined ? undefined : t.has(key) ? t(key) : t("invalid");
  };
}

/** A text rendering of a stored value, kept locally while it is edited. The
 *  buffer is shown only while the stored value is the one it was based on;
 *  undo, another editor or the canvas replacing the value wins. */
function useTextBuffer<T>(
  path: string,
  toText: (value: T) => string,
  fromText: (text: string) => T,
  empty: T,
) {
  const { control, getValues, setValue } = useFormContext();
  const stored = (useWatch({ control, name: path }) ?? empty) as T;
  const serialized = JSON.stringify(stored);
  const [buffer, setBuffer] = useState<{ text: string; basis: string }>();
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      clearTimeout(timer.current);
    };
  }, []);
  const current = buffer?.basis === serialized ? buffer : undefined;

  function commit(text: string) {
    clearTimeout(timer.current);
    // A blur can arrive while the node is being replaced (paste, split).
    if (!alive.current) return;
    const value = fromText(text);
    const next = JSON.stringify(value);
    if (next !== JSON.stringify(getValues(path) ?? empty))
      setValue(path, value, { shouldDirty: true, shouldValidate: true });
    setBuffer({ text, basis: next });
  }

  return {
    text: current?.text ?? toText(stored),
    /** Typing: parse after a pause. Discrete actions commit at once. */
    change(text: string, immediate = false) {
      if (immediate) return commit(text);
      setBuffer({ text, basis: serialized });
      clearTimeout(timer.current);
      timer.current = setTimeout(() => commit(text), IDLE_COMMIT_MS);
    },
    flush() {
      if (current) commit(current.text);
    },
  };
}

type PasteHandler = (current: RichTextSpan[], pasted: RichTextNode[]) => void;

type Shared = {
  baseId: string;
  anchors: () => string[];
  announce: (message: string) => void;
};

export function RichTextField({
  name,
  label,
  disabled = false,
  mediaOptions = [],
  onUploadImage,
  allowedNodes = ALL_NODES,
}: {
  /** RHF path of the node array, e.g. `blocks.3.data.content`. */
  name: string;
  label: string;
  disabled?: boolean;
  /** Ready media assets a figure may show. */
  mediaOptions?: readonly RichTextMediaOption[];
  /** Offers upload-and-crop on figures; called with the new asset id after
   *  it is set, so the owner can refresh `mediaOptions`. */
  onUploadImage?: (assetId: string) => void;
  /** The aside panel allows only `["paragraph", "list"]`. */
  allowedNodes?: readonly NodeType[];
}) {
  const t = useTranslations("Sites.richText");
  const baseId = useId();
  const { control, getValues } = useFormContext();
  const nodes = useFieldArray({ control, name });
  const values = (useWatch({ control, name }) ?? []) as RichTextNode[];
  const fieldError = useErrorText(name)("", false);
  const [active, setActive] = useState<number>();
  const [status, setStatus] = useState("");
  const pendingFocus = useRef<number>(undefined);
  // Anchors given at insertion, before the heading had text: the first text
  // written replaces them once. Later text edits never touch the anchor.
  const [provisional] = useState(() => new Set<string>());

  const anchors = () => {
    const blocks = getValues("blocks") as unknown;
    return collectAnchors(blocks === undefined ? getValues(name) : blocks);
  };

  useEffect(() => {
    if (pendingFocus.current === undefined) return;
    document.getElementById(`${baseId}-${pendingFocus.current}-main`)?.focus();
    pendingFocus.current = undefined;
  }, [nodes.fields, baseId]);

  function newNode(kind: Insertion): RichTextNode {
    switch (kind) {
      case "paragraph":
        return { type: "paragraph", content: [] };
      case "heading2":
      case "heading3":
      case "heading4": {
        const anchor = richTextAnchorSlug("", new Set(anchors()));
        provisional.add(anchor);
        const level = Number(kind.slice(-1)) as 2 | 3 | 4;
        return { type: "heading", level, anchor, text: "" };
      }
      case "bulletList":
      case "orderedList":
        return {
          type: "list",
          style: kind === "bulletList" ? "bullet" : "ordered",
          items: [],
        };
      case "quote":
        return { type: "quote", content: [], author: "", source: "", href: "" };
      case "note":
        return { type: "note", tone: "info", title: "", content: [] };
      case "figure":
        return {
          type: "figure",
          image: { asset_id: "", alt: "" },
          caption: "",
          width: "column",
        };
    }
  }

  function insert(kind: Insertion) {
    const at = Math.min(
      (active ?? nodes.fields.length - 1) + 1,
      nodes.fields.length,
    );
    nodes.insert(at, newNode(kind), { shouldFocus: false });
    pendingFocus.current = at;
    setActive(at);
  }

  /** Replaces one node with several as a single history step. */
  function replaceNode(index: number, replacement: RichTextNode[]) {
    const next = structuredClone((getValues(name) ?? []) as RichTextNode[]);
    next.splice(index, 1, ...replacement);
    nodes.replace(next.slice(0, MAX_NODES));
    pendingFocus.current = Math.min(index + replacement.length, MAX_NODES) - 1;
    setActive(pendingFocus.current);
  }

  function remove(index: number) {
    nodes.remove(index);
    setActive(undefined);
    setStatus(t("removed"));
  }

  const shared: Shared = { baseId, anchors, announce: setStatus };
  const headings = values.flatMap((node, index) =>
    node?.type === "heading" ? [{ node, index }] : [],
  );
  const insertions = INSERTIONS.filter(([, type]) =>
    allowedNodes.includes(type),
  );

  return (
    <FieldSet
      className="gap-3 rounded-lg border border-dashed p-3"
      data-invalid={Boolean(fieldError)}
      disabled={disabled}
    >
      <FieldLegend variant="label">{label}</FieldLegend>
      <FieldDescription id={`${baseId}-syntax`}>
        {t("syntaxHint")}
      </FieldDescription>
      <div
        aria-label={t("insertGroup")}
        className="flex flex-wrap gap-1"
        role="group"
      >
        {insertions.map(([kind]) => (
          <Button
            disabled={nodes.fields.length >= MAX_NODES}
            key={kind}
            onClick={() => insert(kind)}
            size="sm"
            type="button"
            variant="outline"
          >
            {t(`insert.${kind}`)}
          </Button>
        ))}
      </div>
      {headings.length > 0 && (
        <nav aria-label={t("outline")}>
          <ul className="space-y-0.5 text-sm">
            {headings.map(({ node, index }) => (
              <li
                key={nodes.fields[index]?.id ?? index}
                style={{ paddingInlineStart: `${(node.level - 2) * 1}rem` }}
              >
                <Button
                  className="h-auto px-1 py-0.5"
                  onClick={() =>
                    document.getElementById(`${baseId}-${index}-main`)?.focus()
                  }
                  size="sm"
                  type="button"
                  variant="link"
                >
                  {node.text || t("untitledHeading")}
                </Button>
              </li>
            ))}
          </ul>
        </nav>
      )}
      {nodes.fields.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("empty")}</p>
      )}
      {nodes.fields.map((field, index) => (
        <NodeEditor
          count={nodes.fields.length}
          index={index}
          key={field.id}
          mediaOptions={mediaOptions}
          onFocus={() => setActive(index)}
          onMove={(to) => {
            nodes.move(index, to);
            setActive(to);
          }}
          onPasteNodes={(current, pasted) =>
            replaceNode(
              index,
              current.length > 0
                ? [{ type: "paragraph", content: current }, ...pasted]
                : pasted,
            )
          }
          onRemove={() => remove(index)}
          onReplace={(replacement) => replaceNode(index, replacement)}
          onUploadImage={onUploadImage}
          path={`${name}.${index}`}
          provisional={provisional}
          shared={shared}
          // From the field array, not the watched values: those arrive a
          // render later, and a stale type would register another type's
          // inputs on this node's path.
          type={(field as { type?: NodeType }).type ?? "paragraph"}
        />
      ))}
      <FieldError>{fieldError}</FieldError>
      <p
        aria-live="polite"
        className="text-sm text-muted-foreground"
        role="status"
      >
        {status}
      </p>
    </FieldSet>
  );
}

function NodeEditor({
  count,
  index,
  mediaOptions,
  onFocus,
  onMove,
  onPasteNodes,
  onRemove,
  onReplace,
  onUploadImage,
  path,
  provisional,
  shared,
  type,
}: {
  count: number;
  index: number;
  mediaOptions: readonly RichTextMediaOption[];
  onFocus: () => void;
  onMove: (to: number) => void;
  onPasteNodes: PasteHandler;
  onRemove: () => void;
  onReplace: (replacement: RichTextNode[]) => void;
  onUploadImage?: (assetId: string) => void;
  path: string;
  provisional: Set<string>;
  shared: Shared;
  type: NodeType;
}) {
  const t = useTranslations("Sites.richText");
  const id = `${shared.baseId}-${index}`;
  const nodeError = useErrorText(path)("");
  const props = { id, path, shared };
  const fields =
    type === "heading" ? (
      <HeadingFields {...props} provisional={provisional} />
    ) : type === "list" ? (
      <ListFields {...props} />
    ) : type === "quote" ? (
      <QuoteFields {...props} />
    ) : type === "note" ? (
      <NoteFields {...props} />
    ) : type === "figure" ? (
      <FigureFields
        {...props}
        mediaOptions={mediaOptions}
        onUploadImage={onUploadImage}
      />
    ) : (
      <ParagraphFields
        {...props}
        onPasteNodes={onPasteNodes}
        onReplace={onReplace}
      />
    );
  return (
    <FieldSet
      className="gap-3 rounded-md border p-3"
      data-invalid={Boolean(nodeError)}
      onFocus={onFocus}
    >
      <FieldLegend className="float-left mb-0 pt-2" variant="label">
        {t("nodeLegend", { number: index + 1, type: t(`types.${type}`) })}
      </FieldLegend>
      <div className="flex justify-end">
        <div className="flex gap-1">
          <Button
            aria-label={t("moveUp")}
            disabled={index === 0}
            onClick={() => onMove(index - 1)}
            size="icon"
            type="button"
            variant="ghost"
          >
            <ArrowUpIcon aria-hidden="true" />
          </Button>
          <Button
            aria-label={t("moveDown")}
            disabled={index === count - 1}
            onClick={() => onMove(index + 1)}
            size="icon"
            type="button"
            variant="ghost"
          >
            <ArrowDownIcon aria-hidden="true" />
          </Button>
          <Button
            aria-label={t("remove")}
            onClick={onRemove}
            size="icon"
            type="button"
            variant="ghost"
          >
            <Trash2Icon aria-hidden="true" />
          </Button>
        </div>
      </div>
      {fields}
    </FieldSet>
  );
}

type FieldsProps = { id: string; path: string; shared: Shared };

function ParagraphFields({
  id,
  path,
  shared,
  onPasteNodes,
  onReplace,
}: FieldsProps & {
  onPasteNodes: PasteHandler;
  onReplace: (replacement: RichTextNode[]) => void;
}) {
  const t = useTranslations("Sites.richText");
  return (
    <MarkupArea
      id={`${id}-main`}
      label={t("paragraphText")}
      onPasteNodes={onPasteNodes}
      onSplit={(content) =>
        onReplace(splitParagraph({ type: "paragraph", content }))
      }
      path={`${path}.content`}
      shared={shared}
    />
  );
}

function HeadingFields({
  id,
  path,
  shared,
  provisional,
}: FieldsProps & { provisional: Set<string> }) {
  const t = useTranslations("Sites.richText");
  const { control, getValues, register, setValue } = useFormContext();
  const errorAt = useErrorText(path);
  const anchor = String(useWatch({ control, name: `${path}.anchor` }) ?? "");
  const anchorError = !isRichTextAnchor(anchor)
    ? t("anchorInvalid")
    : shared.anchors().filter((taken) => taken === anchor).length > 1
      ? t("anchorTaken")
      : errorAt("anchor");
  const textError = errorAt("text");
  const text = register(`${path}.text`);
  return (
    <>
      <SelectField
        id={`${id}-level`}
        label={t("headingLevel")}
        options={[2, 3, 4].map((level) => [level, t(`levels.h${level}`)])}
        path={`${path}.level`}
      />
      <Field data-invalid={Boolean(textError)}>
        <FieldLabel htmlFor={`${id}-main`}>{t("headingText")}</FieldLabel>
        <Input
          aria-describedby={textError ? `${id}-text-error` : undefined}
          aria-invalid={Boolean(textError)}
          id={`${id}-main`}
          {...text}
          onBlur={(event) => {
            void text.onBlur(event);
            const current = String(getValues(`${path}.anchor`) ?? "");
            const value = event.target.value.trim();
            if (!value || !provisional.has(current)) return;
            provisional.delete(current);
            const taken = new Set(shared.anchors());
            taken.delete(current);
            setValue(`${path}.anchor`, richTextAnchorSlug(value, taken), {
              shouldDirty: true,
              shouldValidate: true,
            });
          }}
        />
        <FieldError id={`${id}-text-error`}>{textError}</FieldError>
      </Field>
      <Field data-invalid={Boolean(anchorError)}>
        <FieldLabel htmlFor={`${id}-anchor`}>{t("anchor")}</FieldLabel>
        <div className="flex items-center gap-1">
          <span aria-hidden="true" className="text-muted-foreground">
            #
          </span>
          <Input
            aria-describedby={`${id}-anchor-hint${anchorError ? ` ${id}-anchor-error` : ""}`}
            aria-invalid={Boolean(anchorError)}
            autoCapitalize="none"
            id={`${id}-anchor`}
            spellCheck={false}
            {...register(`${path}.anchor`, {
              onChange: () => provisional.delete(anchor),
            })}
          />
        </div>
        <FieldDescription id={`${id}-anchor-hint`}>
          {t("anchorHint", { anchor: `#${anchor}` })}
        </FieldDescription>
        <FieldError id={`${id}-anchor-error`}>{anchorError}</FieldError>
      </Field>
    </>
  );
}

function ListFields({ id, path }: FieldsProps) {
  const t = useTranslations("Sites.richText");
  const error = useErrorText(path)("items");
  const buffer = useTextBuffer(
    `${path}.items`,
    listToText,
    textToListItems,
    [],
  );
  return (
    <>
      <SelectField
        id={`${id}-style`}
        label={t("listStyle")}
        options={(["bullet", "ordered"] as const).map((style) => [
          style,
          t(`styles.${style}`),
        ])}
        path={`${path}.style`}
      />
      <Field data-invalid={Boolean(error)}>
        <FieldLabel htmlFor={`${id}-main`}>{t("listItems")}</FieldLabel>
        <Textarea
          aria-describedby={`${id}-list-hint${error ? ` ${id}-list-error` : ""}`}
          aria-invalid={Boolean(error)}
          id={`${id}-main`}
          onBlur={buffer.flush}
          onChange={(event) => buffer.change(event.target.value)}
          value={buffer.text}
        />
        <FieldDescription id={`${id}-list-hint`}>
          {t("listHint")}
        </FieldDescription>
        <FieldError id={`${id}-list-error`}>{error}</FieldError>
      </Field>
    </>
  );
}

const same = (text: string) => text;

/** An optional text property. Buffered rather than registered: RHF fills a
 *  registered input whose value is absent from the form's *default* values at
 *  the same path, which after a reorder, paste or undo belong to another
 *  node. Required properties (heading text and anchor) are always present. */
function TextInput({
  id,
  label,
  path,
  error,
  hint,
  inputMode,
  required,
}: {
  id: string;
  label: string;
  path: string;
  error?: string;
  hint?: string;
  inputMode?: "url";
  required?: boolean;
}) {
  const buffer = useTextBuffer(path, same, same, "");
  const describedBy = [hint && `${id}-hint`, error && `${id}-error`]
    .filter(Boolean)
    .join(" ");
  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        aria-describedby={describedBy || undefined}
        aria-invalid={Boolean(error)}
        aria-required={required}
        id={id}
        inputMode={inputMode}
        onBlur={buffer.flush}
        onChange={(event) => buffer.change(event.target.value)}
        value={buffer.text}
      />
      {hint && <FieldDescription id={`${id}-hint`}>{hint}</FieldDescription>}
      <FieldError id={`${id}-error`}>{error}</FieldError>
    </Field>
  );
}

/** A closed list of values, written as one step per choice. An absent
 *  optional value shows the first option (the renderer's default). */
function SelectField({
  id,
  label,
  path,
  options,
}: {
  id: string;
  label: string;
  path: string;
  options: readonly (readonly [string | number, string])[];
}) {
  const { control, setValue } = useFormContext();
  const value: unknown = useWatch({ control, name: path });
  return (
    <Field>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <NativeSelect
        id={id}
        onChange={(event) => {
          const chosen = options.find(
            ([option]) => String(option) === event.target.value,
          );
          if (chosen)
            setValue(path, chosen[0], {
              shouldDirty: true,
              shouldValidate: true,
            });
        }}
        value={String(value ?? options[0][0])}
      >
        {options.map(([option, text]) => (
          <option key={option} value={option}>
            {text}
          </option>
        ))}
      </NativeSelect>
    </Field>
  );
}

function QuoteFields({ id, path, shared }: FieldsProps) {
  const t = useTranslations("Sites.richText");
  const errorAt = useErrorText(path);
  return (
    <>
      <MarkupArea
        id={`${id}-main`}
        label={t("quoteText")}
        path={`${path}.content`}
        shared={shared}
      />
      <TextInput
        error={errorAt("author")}
        id={`${id}-author`}
        label={t("quoteAuthor")}
        path={`${path}.author`}
      />
      <TextInput
        error={errorAt("source")}
        id={`${id}-source`}
        label={t("quoteSource")}
        path={`${path}.source`}
      />
      <TextInput
        error={errorAt("href")}
        id={`${id}-href`}
        inputMode="url"
        label={t("quoteHref")}
        path={`${path}.href`}
      />
    </>
  );
}

function NoteFields({ id, path, shared }: FieldsProps) {
  const t = useTranslations("Sites.richText");
  const errorAt = useErrorText(path);
  return (
    <>
      <SelectField
        id={`${id}-tone`}
        label={t("noteTone")}
        options={(["info", "tip", "warning"] as const).map((tone) => [
          tone,
          t(`tones.${tone}`),
        ])}
        path={`${path}.tone`}
      />
      <TextInput
        error={errorAt("title")}
        id={`${id}-title`}
        label={t("noteTitle")}
        path={`${path}.title`}
      />
      <MarkupArea
        id={`${id}-main`}
        label={t("noteText")}
        path={`${path}.content`}
        shared={shared}
      />
    </>
  );
}

function FigureFields({
  id,
  path,
  mediaOptions,
  onUploadImage,
}: FieldsProps & {
  mediaOptions: readonly RichTextMediaOption[];
  onUploadImage?: (assetId: string) => void;
}) {
  const t = useTranslations("Sites.richText");
  const { control, setValue } = useFormContext();
  const errorAt = useErrorText(path);
  const assetPath = `${path}.image.asset_id`;
  const assetId = String(useWatch({ control, name: assetPath }) ?? "");
  // Without an image the whole `image` object is missing after pruning.
  const imageError =
    errorAt("image.asset_id") ?? (assetId ? undefined : errorAt("image"));
  const altError = assetId ? errorAt("image.alt") : undefined;
  const choose = (value: string) =>
    setValue(assetPath, value, { shouldDirty: true, shouldValidate: true });
  return (
    <>
      <Field data-invalid={Boolean(imageError)}>
        <FieldLabel htmlFor={`${id}-main`}>{t("figureImage")}</FieldLabel>
        <div className="flex flex-wrap items-center gap-2">
          {/* Controlled: an upload sets an id the options learn only later. */}
          <NativeSelect
            aria-describedby={imageError ? `${id}-image-error` : undefined}
            aria-invalid={Boolean(imageError)}
            className="flex-1"
            id={`${id}-main`}
            onChange={(event) => choose(event.target.value)}
            value={assetId}
          >
            <option value="">{t("noImage")}</option>
            {assetId &&
            !mediaOptions.some((option) => option.id === assetId) ? (
              <option value={assetId}>{t("currentImage")}</option>
            ) : null}
            {mediaOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </NativeSelect>
          {onUploadImage ? (
            <ImageCropUpload
              aspect={[3, 2]}
              label={t("uploadImage")}
              onUploaded={(uploaded) => {
                choose(uploaded);
                onUploadImage(uploaded);
              }}
            />
          ) : null}
        </div>
        <FieldError id={`${id}-image-error`}>{imageError}</FieldError>
      </Field>
      <TextInput
        error={altError}
        hint={t("figureAltHint")}
        id={`${id}-alt`}
        label={t("figureAlt")}
        path={`${path}.image.alt`}
        required={Boolean(assetId)}
      />
      <SelectField
        id={`${id}-width`}
        label={t("figureWidth")}
        options={(["column", "wide"] as const).map((width) => [
          width,
          t(`widths.${width}`),
        ])}
        path={`${path}.width`}
      />
      <TextInput
        error={errorAt("caption")}
        id={`${id}-caption`}
        label={t("figureCaption")}
        path={`${path}.caption`}
      />
    </>
  );
}

const trailingStars = (text: string) => /\**$/.exec(text)?.[0].length ?? 0;
const leadingStars = (text: string) => /^\**/.exec(text)?.[0].length ?? 0;

/** A run editor: the text notation in a textarea, B / I / link buttons and
 *  Ctrl/Cmd+B / Ctrl/Cmd+I that wrap the selection, paste normalisation. */
function MarkupArea({
  id,
  label,
  path,
  shared,
  onPasteNodes,
  onSplit,
}: {
  id: string;
  label: string;
  path: string;
  shared: Shared;
  onPasteNodes?: PasteHandler;
  onSplit?: (content: RichTextSpan[]) => void;
}) {
  const t = useTranslations("Sites.richText");
  const error = useErrorText(path)("");
  const buffer = useTextBuffer(path, spansToMarkup, markupToSpans, []);
  const text = buffer.text;
  const area = useRef<HTMLTextAreaElement>(null);
  const urlInput = useRef<HTMLInputElement>(null);
  const nextSelection = useRef<[number, number]>(undefined);
  const linkRange = useRef<[number, number]>([0, 0]);
  const [link, setLink] = useState<{ url: string; invalid: boolean }>();

  // Restores the caret after a programmatic edit (a controlled value moves it
  // to the end otherwise).
  useLayoutEffect(() => {
    const range = nextSelection.current;
    if (!range || !area.current) return;
    nextSelection.current = undefined;
    area.current.focus();
    area.current.setSelectionRange(range[0], range[1]);
  });
  useEffect(() => {
    if (link && !link.invalid) urlInput.current?.focus();
  }, [link]);

  function selection(): [number, number] {
    const element = area.current;
    return element
      ? [element.selectionStart, element.selectionEnd]
      : [text.length, text.length];
  }

  function replaceSelection(snippet: string, [start, end] = selection()) {
    nextSelection.current = [start + snippet.length, start + snippet.length];
    buffer.change(text.slice(0, start) + snippet + text.slice(end), true);
  }

  function toggleMark(delimiter: "**" | "*") {
    const [start, end] = selection();
    const before = text.slice(0, start);
    const after = text.slice(end);
    const run = Math.min(trailingStars(before), leadingStars(after));
    const active = delimiter === "*" ? run === 1 || run === 3 : run >= 2;
    const size = delimiter.length;
    const next = active
      ? before.slice(0, -size) + text.slice(start, end) + after.slice(size)
      : before + delimiter + text.slice(start, end) + delimiter + after;
    const shift = active ? -size : size;
    nextSelection.current = [start + shift, end + shift];
    buffer.change(next, true);
  }

  function applyLink() {
    const url = link?.url.trim() ?? "";
    if (!isRichTextHref(url)) {
      setLink({ url, invalid: true });
      urlInput.current?.focus();
      return;
    }
    const [start, end] = linkRange.current;
    replaceSelection(linkMarkup(text.slice(start, end), url), [start, end]);
    setLink(undefined);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    const key = event.key.toLowerCase();
    if (key !== "b" && key !== "i") return;
    event.preventDefault();
    toggleMark(key === "b" ? "**" : "*");
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const html = event.clipboardData.getData("text/html");
    const plain = event.clipboardData.getData("text/plain");
    if (!html && !plain) return;
    event.preventDefault();
    const parsed = html
      ? htmlToRichNodes(html, new Set(shared.anchors()))
      : { nodes: plainTextToRichNodes(plain), droppedImages: false };
    const notice = parsed.droppedImages ? ` ${t("imagesDropped")}` : "";
    const structured =
      parsed.nodes.length > 1 ||
      parsed.nodes.some((node) => node.type !== "paragraph");
    if (onPasteNodes && structured) {
      onPasteNodes(markupToSpans(text), parsed.nodes);
      shared.announce(t("pasted", { count: parsed.nodes.length }) + notice);
      return;
    }
    // One paragraph (or a field that holds only runs): paste at the caret,
    // escaped, so stars and brackets from the clipboard stay literal.
    const first = parsed.nodes[0];
    const spans =
      parsed.nodes.length === 1 && first?.type === "paragraph"
        ? first.content
        : [{ text: plain }];
    const snippet = spansToMarkup(spans);
    if (snippet) replaceSelection(snippet);
    if (notice) shared.announce(notice.trim());
  }

  const describedBy = [
    `${shared.baseId}-syntax`,
    error ? `${id}-error` : undefined,
  ]
    .filter(Boolean)
    .join(" ");
  const keepSelection = (event: { preventDefault: () => void }) =>
    event.preventDefault();

  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <div aria-label={t("formatting")} className="flex gap-1" role="group">
        <Button
          aria-controls={id}
          aria-keyshortcuts="Control+B Meta+B"
          aria-label={t("bold")}
          onClick={() => toggleMark("**")}
          onMouseDown={keepSelection}
          size="icon"
          type="button"
          variant="ghost"
        >
          <BoldIcon aria-hidden="true" />
        </Button>
        <Button
          aria-controls={id}
          aria-keyshortcuts="Control+I Meta+I"
          aria-label={t("italic")}
          onClick={() => toggleMark("*")}
          onMouseDown={keepSelection}
          size="icon"
          type="button"
          variant="ghost"
        >
          <ItalicIcon aria-hidden="true" />
        </Button>
        <Button
          aria-expanded={Boolean(link)}
          aria-label={t("link")}
          onClick={() => {
            linkRange.current = selection();
            setLink({ url: "", invalid: false });
          }}
          onMouseDown={keepSelection}
          size="icon"
          type="button"
          variant="ghost"
        >
          <LinkIcon aria-hidden="true" />
        </Button>
      </div>
      <Textarea
        aria-describedby={describedBy}
        aria-invalid={Boolean(error)}
        id={id}
        onBlur={buffer.flush}
        onChange={(event) => buffer.change(event.target.value)}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        ref={area}
        value={text}
      />
      <FieldError id={`${id}-error`}>{error}</FieldError>
      {link && (
        <div className="space-y-2 rounded-md border p-2">
          <Field data-invalid={link.invalid}>
            <FieldLabel htmlFor={`${id}-url`}>{t("linkUrl")}</FieldLabel>
            <Input
              aria-describedby={`${id}-url-hint${link.invalid ? ` ${id}-url-error` : ""}`}
              aria-invalid={link.invalid}
              id={`${id}-url`}
              inputMode="url"
              onChange={(event) =>
                setLink({ url: event.target.value, invalid: false })
              }
              onKeyDown={(event) => {
                // Enter would submit the page form around this field.
                if (event.key === "Enter") {
                  event.preventDefault();
                  applyLink();
                } else if (event.key === "Escape") {
                  event.preventDefault();
                  setLink(undefined);
                  area.current?.focus();
                }
              }}
              ref={urlInput}
              value={link.url}
            />
            <FieldDescription id={`${id}-url-hint`}>
              {t("linkHint")}
            </FieldDescription>
            <FieldError id={`${id}-url-error`}>
              {link.invalid ? t("linkInvalid") : undefined}
            </FieldError>
          </Field>
          <div className="flex gap-2">
            <Button onClick={applyLink} size="sm" type="button">
              {t("linkApply")}
            </Button>
            <Button
              onClick={() => {
                setLink(undefined);
                area.current?.focus();
              }}
              size="sm"
              type="button"
              variant="ghost"
            >
              {t("linkCancel")}
            </Button>
          </div>
        </div>
      )}
      {onSplit && hasBlankLines(text) && (
        <Button
          className="self-start"
          onClick={() => onSplit(markupToSpans(text))}
          size="sm"
          type="button"
          variant="outline"
        >
          {t("split")}
        </Button>
      )}
    </Field>
  );
}
