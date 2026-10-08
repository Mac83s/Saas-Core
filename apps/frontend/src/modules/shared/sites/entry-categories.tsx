"use client";

import { useEffect, useState } from "react";
import { FolderTreeIcon, PlusIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  createTerm,
  listTerms,
  setContentEntryCategories,
  type ContentEntry,
  type TermList,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { Link } from "#i18n/navigation";
import { contentTypeHref } from "./content-types-panel";
import { sitesErrorMessage } from "./problem";

/** The categories an entry is filed under: the type's tree as checkboxes, up
 *  to the limit the server states. A category can be made on the spot — a
 *  small blog's tree is a handful of words, and leaving the entry to make one
 *  costs more than the tree is worth. What is ticked is the entry's draft;
 *  the site shows it once the entry is published again. */
export function EntryCategories({
  entry,
  siteId,
  onChanged,
}: {
  entry: ContentEntry;
  siteId: string;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("Sites");
  const [list, setList] = useState<TermList>();
  const [ticked, setTicked] = useState(
    () => new Set(entry.categories.map((category) => category.id)),
  );
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  useEffect(() => {
    let current = true;
    listTerms(entry.collection_id, "categories")
      .then((result) => {
        if (current) setList(result);
      })
      .catch((error: unknown) => {
        if (current) setProblem(sitesErrorMessage(error, t));
      });
    return () => {
      current = false;
    };
  }, [entry.collection_id, t]);

  const max = list?.max_per_entry ?? Infinity;
  const full = ticked.size >= max;

  function toggle(id: string, on: boolean) {
    setTicked((previous) => {
      const next = new Set(previous);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  async function add() {
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    setProblem(undefined);
    try {
      const made = await createTerm(entry.collection_id, {
        kind: "categories",
        name: trimmed,
      });
      setList(await listTerms(entry.collection_id, "categories"));
      if (!full) toggle(made.id, true);
      setName("");
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!list) return;
    setBusy(true);
    setProblem(undefined);
    try {
      await setContentEntryCategories(
        entry.id,
        list.terms.filter((term) => ticked.has(term.id)).map((term) => term.id),
      );
      await onChanged();
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <FolderTreeIcon aria-hidden="true" className="size-4" />
        <span className="font-medium">{t("entryCategories.title")}</span>
        {entry.categories.map((category) => (
          <Badge key={category.id} variant="secondary">
            {category.name}
          </Badge>
        ))}
      </div>
      {list === undefined && !problem ? (
        <p className="text-sm text-muted-foreground">
          {t("entryCategories.loading")}
        </p>
      ) : null}
      {list && list.terms.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t("entryCategories.empty")}
        </p>
      ) : null}
      {list && list.terms.length > 0 ? (
        <fieldset className="space-y-1">
          <legend className="sr-only">{t("entryCategories.title")}</legend>
          {list.terms.map((term) => (
            <label
              className="flex items-center gap-2 text-sm"
              key={term.id}
              style={{ paddingInlineStart: `${(term.depth - 1) * 1.25}rem` }}
            >
              <input
                checked={ticked.has(term.id)}
                disabled={busy || (full && !ticked.has(term.id))}
                onChange={(event) => toggle(term.id, event.target.checked)}
                type="checkbox"
              />
              <span>{term.name}</span>
            </label>
          ))}
        </fieldset>
      ) : null}
      {list && full ? (
        <p className="text-sm text-muted-foreground">
          {t("entryCategories.limit", { max: list.max_per_entry })}
        </p>
      ) : null}
      {list ? (
        <div className="flex flex-wrap items-end gap-2">
          <Field className="w-auto min-w-48 flex-1">
            <FieldLabel htmlFor={`category-new-${entry.id}`}>
              {t("entryCategories.newLabel")}
            </FieldLabel>
            <Input
              disabled={busy}
              id={`category-new-${entry.id}`}
              onChange={(event) => setName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                event.preventDefault();
                void add();
              }}
              value={name}
            />
          </Field>
          <Button
            disabled={busy || !name.trim()}
            onClick={() => void add()}
            size="sm"
            type="button"
            variant="outline"
          >
            <PlusIcon aria-hidden="true" />
            {t("entryCategories.add")}
          </Button>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          disabled={busy || !list}
          onClick={() => void save()}
          size="sm"
          type="button"
        >
          {t("entryCategories.save")}
        </Button>
        <Link
          className="text-sm underline"
          href={contentTypeHref(siteId, entry.collection_id, "/categories")}
        >
          {t("entryCategories.manage")}
        </Link>
      </div>
      <p className="text-sm text-muted-foreground">
        {t("entryCategories.hint")}
      </p>
      {problem && (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}
