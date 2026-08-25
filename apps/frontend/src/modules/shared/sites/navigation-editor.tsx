"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  ArrowDownIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  ArrowUpIcon,
  EyeIcon,
  EyeOffIcon,
  RefreshCwIcon,
  SaveIcon,
} from "lucide-react";

import {
  getSiteNavigation,
  saveSiteNavigation,
  type PageSummary,
  type SiteNavigation as SiteNavigationResult,
  type SiteNavigationItem,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";

import { sitesErrorMessage } from "./problem";

type Entry = {
  page_id: string;
  parent_page_id: string | null;
  visible: boolean;
};

/** Reordering is expressed as commands rather than drag coordinates. Every move
 *  is therefore reachable from the keyboard by construction, which ADR-031 makes
 *  an acceptance gate — pointer dragging can be layered on later and reuse the
 *  same operations. */
function move(entries: Entry[], index: number, delta: number): Entry[] {
  const target = index + delta;
  if (target < 0 || target >= entries.length) return entries;
  const next = [...entries];
  [next[index], next[target]] = [next[target], next[index]];
  return next;
}

/** Indenting adopts the nearest top-level entry above. Only one level is
 *  allowed, matching what the published menu renders. */
function indent(entries: Entry[], index: number): Entry[] {
  const entry = entries[index];
  if (entry.parent_page_id !== null) return entries;
  const parent = entries
    .slice(0, index)
    .reverse()
    .find((candidate) => candidate.parent_page_id === null);
  if (parent === undefined) return entries;
  const next = [...entries];
  next[index] = { ...entry, parent_page_id: parent.page_id };
  return next;
}

function outdent(entries: Entry[], index: number): Entry[] {
  const entry = entries[index];
  if (entry.parent_page_id === null) return entries;
  const next = [...entries];
  next[index] = { ...entry, parent_page_id: null };
  return next;
}

export function NavigationEditor({
  pages,
  siteId,
}: {
  pages: PageSummary[];
  siteId: string;
}) {
  const t = useTranslations("Sites");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [conflict, setConflict] = useState(false);
  const [saved, setSaved] = useState(false);

  const apply = useCallback((navigation: SiteNavigationResult) => {
    setEntries(
      navigation.items.map((item: SiteNavigationItem) => ({
        page_id: item.page_id,
        parent_page_id: item.parent_page_id ?? null,
        visible: item.visible ?? true,
      })),
    );
    setVersion(navigation.version);
    setConflict(false);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setProblem(undefined);
    try {
      apply(await getSiteNavigation(siteId));
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setLoading(false);
    }
  }, [apply, siteId, t]);

  // The first load runs from the effect without touching state up front:
  // `loading` already starts true, and setting it again synchronously here
  // would queue a cascading render.
  useEffect(() => {
    let mounted = true;
    void getSiteNavigation(siteId)
      .then((navigation) => {
        if (mounted) apply(navigation);
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
  }, [apply, siteId, t]);

  const inMenu = new Set(entries.map((entry) => entry.page_id));
  const available = pages.filter((page) => !inMenu.has(page.id));
  const pageName = (pageId: string) =>
    pages.find((page) => page.id === pageId)?.name ?? pageId;

  async function submit() {
    setSaving(true);
    setProblem(undefined);
    setSaved(false);
    try {
      const navigation = await saveSiteNavigation(siteId, {
        expected_version: version,
        items: entries,
      });
      setVersion(navigation.version);
      setConflict(false);
      setSaved(true);
    } catch (error) {
      // The menu is edited as a whole, so a conflict cannot be merged field by
      // field: the operator is told, and their arrangement is kept on screen
      // until they decide to reload it.
      setConflict(true);
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("navigationTitle")}</CardTitle>
        <CardDescription>{t("navigationDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
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
            {t("navigationSaved")}
          </p>
        )}

        {entries.length === 0 ? (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            {t("navigationEmpty")}
          </p>
        ) : (
          <ol className="space-y-2">
            {entries.map((entry, index) => (
              <li
                className={entry.parent_page_id === null ? "" : "ml-6"}
                key={entry.page_id}
              >
                <div className="flex flex-wrap items-center gap-2 rounded-lg border p-2">
                  <span className="flex-1 truncate font-medium">
                    {pageName(entry.page_id)}
                  </span>
                  {!entry.visible && (
                    <Badge variant="secondary">{t("navigationHidden")}</Badge>
                  )}
                  <Button
                    aria-label={t("navigationMoveUp", {
                      name: pageName(entry.page_id),
                    })}
                    disabled={index === 0}
                    onClick={() => setEntries(move(entries, index, -1))}
                    size="icon"
                    type="button"
                    variant="ghost"
                  >
                    <ArrowUpIcon aria-hidden="true" />
                  </Button>
                  <Button
                    aria-label={t("navigationMoveDown", {
                      name: pageName(entry.page_id),
                    })}
                    disabled={index === entries.length - 1}
                    onClick={() => setEntries(move(entries, index, 1))}
                    size="icon"
                    type="button"
                    variant="ghost"
                  >
                    <ArrowDownIcon aria-hidden="true" />
                  </Button>
                  <Button
                    aria-label={t("navigationIndent", {
                      name: pageName(entry.page_id),
                    })}
                    disabled={entry.parent_page_id !== null || index === 0}
                    onClick={() => setEntries(indent(entries, index))}
                    size="icon"
                    type="button"
                    variant="ghost"
                  >
                    <ArrowRightIcon aria-hidden="true" />
                  </Button>
                  <Button
                    aria-label={t("navigationOutdent", {
                      name: pageName(entry.page_id),
                    })}
                    disabled={entry.parent_page_id === null}
                    onClick={() => setEntries(outdent(entries, index))}
                    size="icon"
                    type="button"
                    variant="ghost"
                  >
                    <ArrowLeftIcon aria-hidden="true" />
                  </Button>
                  <Button
                    aria-label={t(
                      entry.visible ? "navigationHide" : "navigationShow",
                      { name: pageName(entry.page_id) },
                    )}
                    onClick={() =>
                      setEntries(
                        entries.map((candidate, candidateIndex) =>
                          candidateIndex === index
                            ? { ...candidate, visible: !candidate.visible }
                            : candidate,
                        ),
                      )
                    }
                    size="icon"
                    type="button"
                    variant="ghost"
                  >
                    {entry.visible ? (
                      <EyeIcon aria-hidden="true" />
                    ) : (
                      <EyeOffIcon aria-hidden="true" />
                    )}
                  </Button>
                  <Button
                    onClick={() =>
                      setEntries(
                        entries.filter(
                          (candidate) =>
                            candidate.page_id !== entry.page_id &&
                            candidate.parent_page_id !== entry.page_id,
                        ),
                      )
                    }
                    size="sm"
                    type="button"
                    variant="ghost"
                  >
                    {t("navigationRemove")}
                  </Button>
                </div>
              </li>
            ))}
          </ol>
        )}

        {available.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-sm font-medium">{t("navigationAddTitle")}</h4>
            <div className="flex flex-wrap gap-2">
              {available.map((page) => (
                <Button
                  key={page.id}
                  onClick={() =>
                    setEntries([
                      ...entries,
                      {
                        page_id: page.id,
                        parent_page_id: null,
                        visible: true,
                      },
                    ])
                  }
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  {page.name}
                </Button>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <Button disabled={loading || saving} onClick={submit} type="button">
            <SaveIcon aria-hidden="true" />
            {saving ? t("navigationSaving") : t("navigationSave")}
          </Button>
          <Button
            disabled={loading || saving}
            onClick={() => void load()}
            type="button"
            variant={conflict ? "default" : "outline"}
          >
            <RefreshCwIcon aria-hidden="true" />
            {t("navigationReload")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
