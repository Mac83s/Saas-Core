"use client";

import { useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { FileTextIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { Controller, useForm, type SubmitHandler } from "react-hook-form";
import { z } from "zod";

import {
  updateContentEntryMetadata,
  type ContentEntry,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { Switch } from "@saas-core/ui/components/switch";
import { Textarea } from "@saas-core/ui/components/textarea";

import { sitesErrorMessage } from "./problem";

type MetadataValues = {
  title: string;
  excerpt: string;
  author_name: string;
  noindex: boolean;
};

/** What an article says about itself apart from its text. Visitors see a
 *  change with the article's next publication, as with its text. */
export function EntryMetadata({
  entry,
  onChanged,
}: {
  entry: ContentEntry;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("Sites");
  const [problem, setProblem] = useState<string>();
  const [saved, setSaved] = useState(false);
  const schema = useMemo(
    () =>
      z.object({
        title: z.string().trim().min(1, t("entryTitleRequired")).max(200),
        excerpt: z.string().max(400),
        author_name: z.string().max(120),
        noindex: z.boolean(),
      }),
    [t],
  );
  const form = useForm<MetadataValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: entry.title,
      excerpt: entry.excerpt,
      author_name: entry.author_name,
      noindex: entry.noindex,
    },
  });

  const submit: SubmitHandler<MetadataValues> = async (values) => {
    setProblem(undefined);
    setSaved(false);
    try {
      await updateContentEntryMetadata(entry.id, values);
      setSaved(true);
      await onChanged();
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    }
  };

  const id = (field: string) => `entry-${field}-${entry.id}`;
  return (
    <form
      aria-labelledby={id("heading")}
      className="space-y-3 rounded-lg border p-4"
      onSubmit={(event) => {
        void form.handleSubmit(submit)(event);
      }}
    >
      <div className="flex items-center gap-2">
        <FileTextIcon aria-hidden="true" className="size-4" />
        <span className="font-medium" id={id("heading")}>
          {t("entryMetadataTitle")}
        </span>
      </div>
      {entry.translation_of && (
        <p className="text-sm text-muted-foreground">
          {t("entryMetadataTranslationHint")}
        </p>
      )}
      <Field>
        <FieldLabel htmlFor={id("title")}>{t("entryTitle")}</FieldLabel>
        <Input
          aria-invalid={Boolean(form.formState.errors.title)}
          id={id("title")}
          {...form.register("title")}
        />
        {form.formState.errors.title && (
          <FieldError>{form.formState.errors.title.message}</FieldError>
        )}
      </Field>
      <Field>
        <FieldLabel htmlFor={id("excerpt")}>{t("entryExcerpt")}</FieldLabel>
        <Textarea id={id("excerpt")} rows={3} {...form.register("excerpt")} />
      </Field>
      <Field>
        <FieldLabel htmlFor={id("author")}>{t("entryAuthor")}</FieldLabel>
        <Input id={id("author")} {...form.register("author_name")} />
      </Field>
      <label className="flex min-h-11 items-center gap-3 text-sm">
        <Controller
          control={form.control}
          name="noindex"
          render={({ field }) => (
            <Switch
              checked={field.value}
              onCheckedChange={(checked) => field.onChange(checked)}
            />
          )}
        />
        {t("entryNoindex")}
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={form.formState.isSubmitting} size="sm" type="submit">
          {t("entryMetadataSave")}
        </Button>
        {saved && !problem && (
          <span className="text-sm text-muted-foreground" role="status">
            {t("entryMetadataSaved")}
          </span>
        )}
      </div>
      {problem && (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      )}
    </form>
  );
}
