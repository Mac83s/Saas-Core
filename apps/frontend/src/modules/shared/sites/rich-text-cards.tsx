"use client";

/** Quotes, notes and figures in the WYSIWYG editor (ADR-056): cards inside
 *  the text. A quote's or a note's own text is edited in place like any
 *  paragraph; the fields around it (author, tone, image…) are plain inputs
 *  that write the node's attributes. Empty inputs leave the field absent, as
 *  the contract's optional fields are. */

import type { AnyExtension } from "@tiptap/core";
import {
  NodeViewContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  type ReactNodeViewProps,
} from "@tiptap/react";
import { Trash2Icon } from "lucide-react";
import { useTranslations } from "next-intl";
import { createContext, useContext, useId } from "react";

import { Button } from "@saas-core/ui/components/button";
import {
  Field,
  FieldDescription,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { GenerateImageDialog } from "../image-generation/generate-image-dialog";
import { ImageCropUpload } from "../media/crop";
import { PageEditorContext } from "./page-editor-context";
import { PrivateMediaPreview } from "./private-media-preview";

export type RichTextMediaOption = { id: string; label: string };

/** Ready media a figure may show, and the upload that adds one. */
export const RichTextMediaContext = createContext<{
  options: readonly RichTextMediaOption[];
  onUpload?: (assetId: string) => void;
}>({ options: [] });

const QUOTE_HREF = /^(?:\/(?!\/)|https:\/\/|mailto:|tel:)/;

type Attrs = Record<string, string | null>;

function TextField({
  label,
  value,
  onChange,
  invalid,
  hint,
}: {
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
  invalid?: string;
  hint?: string;
}) {
  const id = useId();
  return (
    <Field data-invalid={Boolean(invalid)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        aria-describedby={hint || invalid ? `${id}-hint` : undefined}
        aria-invalid={Boolean(invalid)}
        id={id}
        onChange={(event) => onChange(event.target.value || null)}
        value={value ?? ""}
      />
      {(invalid ?? hint) && (
        <FieldDescription id={`${id}-hint`}>{invalid ?? hint}</FieldDescription>
      )}
    </Field>
  );
}

function CardHeader({
  label,
  onRemove,
}: {
  label: string;
  onRemove: () => void;
}) {
  const t = useTranslations("Sites.richText");
  return (
    <div className="rich-text-card__header" contentEditable={false}>
      <span>{label}</span>
      <Button
        aria-label={`${t("remove")}: ${label}`}
        onClick={onRemove}
        size="icon-sm"
        type="button"
        variant="ghost"
      >
        <Trash2Icon aria-hidden />
      </Button>
    </div>
  );
}

function QuoteView({ node, updateAttributes, deleteNode }: ReactNodeViewProps) {
  const t = useTranslations("Sites.richText");
  const attrs = node.attrs as Attrs;
  const href = attrs.href;
  return (
    <NodeViewWrapper
      as="blockquote"
      className="rich-text-card rich-text-card--quote"
    >
      <CardHeader label={t("types.quote")} onRemove={deleteNode} />
      <NodeViewContent className="rich-text-card__text" />
      <div className="rich-text-card__fields" contentEditable={false}>
        <TextField
          label={t("quoteAuthor")}
          onChange={(author) => updateAttributes({ author })}
          value={attrs.author}
        />
        <TextField
          label={t("quoteSource")}
          onChange={(source) => updateAttributes({ source })}
          value={attrs.source}
        />
        <TextField
          invalid={
            href && !QUOTE_HREF.test(href) ? t("linkInvalid") : undefined
          }
          label={t("quoteHref")}
          onChange={(value) => updateAttributes({ href: value })}
          value={href}
        />
      </div>
    </NodeViewWrapper>
  );
}

function NoteView({ node, updateAttributes, deleteNode }: ReactNodeViewProps) {
  const t = useTranslations("Sites.richText");
  const id = useId();
  const attrs = node.attrs as Attrs;
  return (
    <NodeViewWrapper
      as="aside"
      className="rich-text-card rich-text-card--note"
      data-tone={attrs.tone ?? "info"}
    >
      <CardHeader label={t("types.note")} onRemove={deleteNode} />
      <div className="rich-text-card__fields" contentEditable={false}>
        <Field>
          <FieldLabel htmlFor={id}>{t("noteTone")}</FieldLabel>
          <NativeSelect
            id={id}
            onChange={(event) => updateAttributes({ tone: event.target.value })}
            value={attrs.tone ?? "info"}
          >
            {(["info", "tip", "warning"] as const).map((tone) => (
              <option key={tone} value={tone}>
                {t(`tones.${tone}`)}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <TextField
          label={t("noteTitle")}
          onChange={(title) => updateAttributes({ title })}
          value={attrs.title}
        />
      </div>
      <NodeViewContent className="rich-text-card__text" />
    </NodeViewWrapper>
  );
}

function FigureView({
  node,
  updateAttributes,
  deleteNode,
}: ReactNodeViewProps) {
  const t = useTranslations("Sites.richText");
  const media = useContext(RichTextMediaContext);
  const offer = useContext(PageEditorContext)?.imageGeneration;
  const id = useId();
  const attrs = node.attrs as Attrs;
  const assetId = attrs.assetId ?? "";
  return (
    <NodeViewWrapper
      as="figure"
      className="rich-text-card rich-text-card--figure"
    >
      <CardHeader label={t("types.figure")} onRemove={deleteNode} />
      <div className="rich-text-card__fields" contentEditable={false}>
        {assetId && (
          <div className="rich-text-card__image">
            <PrivateMediaPreview alt={attrs.alt ?? ""} assetId={assetId} />
          </div>
        )}
        <Field data-invalid={!assetId}>
          <FieldLabel htmlFor={id}>{t("figureImage")}</FieldLabel>
          <div className="flex flex-wrap items-center gap-2">
            {/* Controlled: an upload sets an id the options learn only later. */}
            <NativeSelect
              className="flex-1"
              id={id}
              onChange={(event) =>
                updateAttributes({ assetId: event.target.value })
              }
              value={assetId}
            >
              <option value="">{t("noImage")}</option>
              {assetId &&
              !media.options.some((option) => option.id === assetId) ? (
                <option value={assetId}>{t("currentImage")}</option>
              ) : null}
              {media.options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </NativeSelect>
            {media.onUpload ? (
              <ImageCropUpload
                aspect={[3, 2]}
                label={t("uploadImage")}
                onUploaded={(uploaded) => {
                  updateAttributes({ assetId: uploaded });
                  media.onUpload?.(uploaded);
                }}
              />
            ) : null}
            {offer?.available && offer.aspects.includes("3:2") ? (
              <GenerateImageDialog
                aspect="3:2"
                offer={offer}
                onUse={(generated) => {
                  updateAttributes({ assetId: generated });
                  media.onUpload?.(generated);
                }}
              />
            ) : null}
          </div>
        </Field>
        <TextField
          hint={t("figureAltHint")}
          label={t("figureAlt")}
          onChange={(alt) => updateAttributes({ alt: alt ?? "" })}
          value={attrs.alt}
        />
        <Field>
          <FieldLabel htmlFor={`${id}-width`}>{t("figureWidth")}</FieldLabel>
          <NativeSelect
            id={`${id}-width`}
            onChange={(event) =>
              updateAttributes({ width: event.target.value })
            }
            value={attrs.width ?? "column"}
          >
            {(["column", "wide"] as const).map((width) => (
              <option key={width} value={width}>
                {t(`widths.${width}`)}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <TextField
          label={t("figureCaption")}
          onChange={(caption) => updateAttributes({ caption })}
          value={attrs.caption}
        />
      </div>
    </NodeViewWrapper>
  );
}

const VIEWS = { quote: QuoteView, note: NoteView, figure: FigureView } as const;

/** The schema's card nodes with their editing views; everything else as is. */
export function withCardViews(extensions: AnyExtension[]): AnyExtension[] {
  return extensions.map((extension) => {
    const view = VIEWS[extension.name as keyof typeof VIEWS];
    return view
      ? extension.extend({ addNodeView: () => ReactNodeViewRenderer(view) })
      : extension;
  });
}
