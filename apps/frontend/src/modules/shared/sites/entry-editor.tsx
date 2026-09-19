"use client";

/** Block editing for a collection entry. The blocks, their contract and their
 *  fields are the ones pages use — only the endpoint differs — so a blog post
 *  cannot drift into a second, weaker notion of content. */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useFieldArray, useForm, type SubmitHandler } from "react-hook-form";
import { PlusIcon, RefreshCwIcon, SaveIcon } from "lucide-react";
import { z } from "zod";

import {
  getContentEntryDraft,
  listMediaAssets,
  saveContentEntryDraft,
  type ContentEntry,
  type MediaAsset,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@saas-core/ui/components/combobox";
import { Field, FieldLabel } from "@saas-core/ui/components/field";

import {
  BlockFields,
  blockFormSchema,
  blockOptions,
  blockPayload,
  editableBlocks,
  emptyBlock,
  mediaIdsInBlocks,
  type BlockOption,
} from "./block-form";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { sitesErrorMessage } from "./problem";

const entryDraftSchema = z.object({ blocks: z.array(blockFormSchema) });
type EntryDraftValues = z.infer<typeof entryDraftSchema>;

export function EntryEditor({
  entry,
  locked,
  onSaved,
  proposal,
}: {
  entry: ContentEntry;
  locked: boolean;
  onSaved: () => void;
  proposal: boolean;
}) {
  const t = useTranslations("Sites");
  const [version, setVersion] = useState(entry.version);
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [selectedBlock, setSelectedBlock] = useState<BlockOption | null>(null);
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const receipt = useRef<MutationReceipt | undefined>(undefined);

  const form = useForm<EntryDraftValues>({
    resolver: zodResolver(entryDraftSchema),
    defaultValues: { blocks: [] },
  });
  const blocks = useFieldArray({ control: form.control, name: "blocks" });

  const load = useCallback(async () => {
    setLoading(true);
    setProblem(undefined);
    try {
      const [draft, media] = await Promise.all([
        getContentEntryDraft(entry.id),
        listMediaAssets(),
      ]);
      setVersion(draft.version);
      setAssets(media.items);
      form.reset({ blocks: editableBlocks(asBlocks(draft.blocks)) });
      setConflict(false);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setLoading(false);
    }
  }, [entry.id, form, t]);

  // As in the other panels: `loading` already starts true, so the first load
  // must not set it again from inside the effect.
  useEffect(() => {
    let mounted = true;
    void Promise.all([getContentEntryDraft(entry.id), listMediaAssets()])
      .then(([draft, media]) => {
        if (!mounted) return;
        setVersion(draft.version);
        setAssets(media.items);
        form.reset({ blocks: editableBlocks(asBlocks(draft.blocks)) });
      })
      .catch((error: unknown) => {
        if (mounted) setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [entry.id, form, t]);

  const save: SubmitHandler<EntryDraftValues> = async (values) => {
    setProblem(undefined);
    setSaved(false);
    const payload = {
      expected_version: version,
      blocks: values.blocks.map(blockPayload),
      // Collected from the blocks rather than asked of the operator: a picture
      // the article shows has to be a reference, or storage may reclaim it.
      media_asset_ids: mediaIdsInBlocks(values.blocks),
    };
    try {
      const draft = await saveContentEntryDraft(
        entry.id,
        payload,
        mutationKey(receipt, `entry-draft-${entry.id}`, payload),
      );
      setVersion(draft.version);
      setConflict(false);
      setSaved(true);
      onSaved();
    } catch (error) {
      // A draft is saved whole, so a conflict cannot be merged field by field.
      // The operator keeps what is on screen until they choose to reload.
      setConflict(true);
      setProblem(sitesErrorMessage(error, t));
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("entryEditor")}</CardTitle>
        <CardDescription>
          {t("entryEditorDescription", { title: entry.title })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* The panel does not enforce this — the API does, and it answers 403
            `page_automation_forbidden`. Saying it up front spares the operator
            filling a form that was never going to be accepted. */}
        {/* Under `proposed` the automation wrote this draft and stopped. What
            the operator is looking at is a proposal, and publishing it is the
            act of accepting it — worth saying, because nothing else on screen
            distinguishes it from their own unsaved work. */}
        {proposal && !locked && (
          <p
            className="rounded-lg border border-info-foreground/30 bg-info p-3 text-sm"
            role="status"
          >
            {t("entryProposalHint")}
          </p>
        )}
        {locked && (
          <p
            className="rounded-lg border border-warning-foreground/30 bg-warning p-3 text-sm"
            role="status"
          >
            {t("automationLockedHint")}
          </p>
        )}
        {problem && (
          <div
            className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
            role="alert"
          >
            {problem}
          </div>
        )}
        {saved && !problem && (
          <p className="text-sm text-muted-foreground" role="status">
            {t("draftSaved")}
          </p>
        )}
        {conflict && (
          <Button onClick={() => void load()} type="button" variant="outline">
            <RefreshCwIcon aria-hidden="true" />
            {t("loadServerVersion")}
          </Button>
        )}

        <form
          className="space-y-5"
          onSubmit={(event) => {
            void form.handleSubmit(save)(event);
          }}
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <Field className="flex-1">
              <FieldLabel htmlFor="entry-block-picker">
                {t("addBlock")}
              </FieldLabel>
              <Combobox
                isItemEqualToValue={(item, value) => item.type === value.type}
                itemToStringLabel={(item) => t(item.labelKey)}
                itemToStringValue={(item) => item.type}
                items={blockOptions}
                onValueChange={setSelectedBlock}
                value={selectedBlock}
              >
                <ComboboxInput
                  id="entry-block-picker"
                  placeholder={t("searchBlocks")}
                  triggerLabel={t("openOptions")}
                />
                <ComboboxContent>
                  <ComboboxEmpty>{t("noBlocks")}</ComboboxEmpty>
                  <ComboboxList>
                    {blockOptions.map((option) => (
                      <ComboboxItem key={option.type} value={option}>
                        {t(option.labelKey)}
                      </ComboboxItem>
                    ))}
                  </ComboboxList>
                </ComboboxContent>
              </Combobox>
            </Field>
            <Button
              disabled={!selectedBlock}
              onClick={() => {
                if (!selectedBlock) return;
                blocks.append(emptyBlock(selectedBlock.type));
                setSelectedBlock(null);
              }}
              type="button"
              variant="outline"
            >
              <PlusIcon aria-hidden="true" />
              {t("add")}
            </Button>
          </div>

          <div className="space-y-4">
            {blocks.fields.length === 0 && !loading && (
              <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                {t("emptyBlocks")}
              </p>
            )}
            {blocks.fields.map((field, index) => (
              <BlockFields
                assets={assets}
                form={form}
                index={index}
                isFirst={index === 0}
                isLast={index === blocks.fields.length - 1}
                key={field.id}
                moveDown={() => blocks.swap(index, index + 1)}
                moveUp={() => blocks.swap(index, index - 1)}
                onRemove={() => blocks.remove(index)}
                type={field.block_type}
              />
            ))}
          </div>

          <Button
            disabled={loading || form.formState.isSubmitting}
            type="submit"
          >
            <SaveIcon aria-hidden="true" />
            {form.formState.isSubmitting ? t("saving") : t("saveDraft")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

/** The draft endpoint types blocks as free-form objects, because the contract
 *  that constrains them is the block schema rather than the envelope. */
function asBlocks(
  blocks: readonly Record<string, unknown>[],
): { block_type: string; schema_version: number; data: unknown }[] {
  return blocks.map((block) => ({
    block_type: String(block.block_type ?? ""),
    schema_version: Number(block.schema_version ?? 1),
    data: block.data,
  }));
}
