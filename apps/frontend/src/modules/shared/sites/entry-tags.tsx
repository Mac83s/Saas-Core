"use client";

import { useState } from "react";
import { TagsIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { setContentEntryTags, type ContentEntry } from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { sitesErrorMessage } from "./problem";

/** What an article is about, as a comma-separated line.
 *
 *  A plain field rather than a picker: the vocabulary of a small blog is a
 *  dozen words its author already knows, and a picker of a dozen items costs
 *  more to build and to use than typing them. */
export function EntryTags({
  entry,
  onChanged,
}: {
  entry: ContentEntry;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("Sites");
  const [value, setValue] = useState(() =>
    entry.tags.map((tag) => tag.name).join(", "),
  );
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  function save() {
    setBusy(true);
    setProblem(undefined);
    const names = value
      .split(",")
      .map((name) => name.trim())
      .filter((name) => name.length > 0);
    void setContentEntryTags(entry.id, names)
      .then(() => onChanged())
      .catch((error: unknown) => {
        setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        setBusy(false);
      });
  }

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <TagsIcon aria-hidden="true" className="size-4" />
        <span className="font-medium">{t("tagsTitle")}</span>
        {entry.tags.map((tag) => (
          <Badge key={tag.slug} variant="secondary">
            {tag.name}
          </Badge>
        ))}
      </div>
      <Field>
        <FieldLabel htmlFor={`tags-${entry.id}`}>{t("tagsLabel")}</FieldLabel>
        <Input
          disabled={busy}
          id={`tags-${entry.id}`}
          onChange={(event) => setValue(event.target.value)}
          placeholder={t("tagsPlaceholder")}
          value={value}
        />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={busy} onClick={save} size="sm" type="button">
          {t("tagsSave")}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">{t("tagsHint")}</p>
      {problem && (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}
