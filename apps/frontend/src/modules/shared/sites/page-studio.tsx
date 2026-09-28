"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import {
  getSiteAppearance,
  getSiteNavigation,
  getSiteLocalizationReport,
  saveSiteAppearance,
  type PageSummary,
} from "@saas-core/api-client";
import {
  parseSiteAppearance,
  type SiteAppearance,
  type NavigationLink,
} from "@saas-core/site-blocks";
import { AppearanceEditor } from "./appearance-editor";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import { PageEditor } from "./page-editor";

export function PageStudio({
  page,
  pages = [],
  onChanged,
  onSelectPage,
}: {
  page: PageSummary;
  /** The site's pages: with `onSelectPage`, the studio switches between them
   *  without closing (F3-Z3). */
  pages?: readonly PageSummary[];
  onChanged: () => Promise<void>;
  onSelectPage?: (pageId: string) => void;
}) {
  const t = useTranslations("Sites.studio");
  const [open, setOpen] = useState(true);
  // What waits for "Odrzuć zmiany": closing the studio or another page.
  const [confirmExit, setConfirmExit] = useState<
    false | { close: true } | { pageId: string }
  >(false);
  const [menuOrder, setMenuOrder] = useState<
    { page_id: string; parent_page_id?: string | null }[]
  >([]);
  const [exitState, setExitState] = useState({ dirty: false, busy: true });
  const a = useTranslations("Sites.appearance");
  const [navigation, setNavigation] = useState<NavigationLink[]>([]);
  const [navigationProblem, setNavigationProblem] = useState(false);
  const [appearance, setAppearance] = useState<SiteAppearance>();
  const [savedAppearance, setSavedAppearance] = useState<{
    version: number;
    data: SiteAppearance;
  }>();
  const [appearanceBusy, setAppearanceBusy] = useState(false);
  const [appearanceProblem, setAppearanceProblem] = useState<string>();
  const [reloadAppearance, setReloadAppearance] = useState(0);
  const appearanceReceipt = useRef<MutationReceipt | undefined>(undefined);
  const appearanceDirty = Boolean(
    appearance &&
    savedAppearance &&
    JSON.stringify(appearance) !== JSON.stringify(savedAppearance.data),
  );
  const previewAppearance = useMemo(() => {
    try {
      return appearance ? parseSiteAppearance(appearance) : undefined;
    } catch {
      return savedAppearance?.data;
    }
  }, [appearance, savedAppearance]);
  useEffect(() => {
    if (!open || !page.site_id) return;
    let active = true;
    getSiteAppearance(page.site_id)
      .then((result) => {
        if (!active) return;
        const data = parseSiteAppearance(result.appearance);
        setAppearance(data);
        setSavedAppearance({ version: result.version, data });
        setAppearanceProblem(undefined);
        appearanceReceipt.current = undefined;
      })
      .catch(() => {
        if (active) setAppearanceProblem(a("loadError"));
      });
    return () => {
      active = false;
    };
  }, [open, page.site_id, reloadAppearance, a]);
  useEffect(() => {
    if (!open || !page.site_id) return;
    let active = true;
    Promise.all([
      getSiteNavigation(page.site_id),
      getSiteLocalizationReport(page.site_id),
    ])
      .then(([menu, report]) => {
        if (!active) return;
        setMenuOrder(menu.items);
        const links: NavigationLink[] = [];
        const visible = new Set(
          menu.items.filter((item) => item.visible).map((item) => item.page_id),
        );
        for (const item of menu.items) {
          if (
            !item.visible ||
            (item.parent_page_id && !visible.has(item.parent_page_id))
          )
            continue;
          const localized = report.pages
            .find((entry) => entry.page_id === item.page_id)
            ?.locales.find((entry) => entry.locale === report.default_locale);
          if (!localized?.path || !localized.title) continue;
          links.push({
            page_id: item.page_id,
            parent_page_id: item.parent_page_id ?? null,
            title: localized.title,
            path: localized.path,
          });
        }
        setNavigation(links);
        setNavigationProblem(false);
      })
      .catch(() => {
        if (active) {
          setNavigation([]);
          setNavigationProblem(true);
        }
      });
    return () => {
      active = false;
    };
  }, [open, page.site_id]);
  useEffect(() => {
    if (!appearanceDirty) return;
    const preventLoss = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", preventLoss);
    return () => window.removeEventListener("beforeunload", preventLoss);
  }, [appearanceDirty]);
  async function saveAppearance() {
    if (!appearance || !savedAppearance) return;
    try {
      parseSiteAppearance(appearance);
    } catch {
      setAppearanceProblem(a("invalid"));
      return;
    }
    const input = {
      expected_version: savedAppearance.version,
      appearance: JSON.parse(JSON.stringify(appearance)),
    };
    setAppearanceBusy(true);
    setAppearanceProblem(undefined);
    try {
      const result = await saveSiteAppearance(
        page.site_id,
        input,
        mutationKey(appearanceReceipt, `appearance-${page.site_id}`, input),
      );
      const data = parseSiteAppearance(result.appearance);
      setAppearance(data);
      setSavedAppearance({ version: result.version, data });
      appearanceReceipt.current = undefined;
    } catch {
      setAppearanceProblem(a("saveError"));
    } finally {
      setAppearanceBusy(false);
    }
  }
  const appearanceControls = (
    <>
      {navigationProblem && (
        <p className="text-sm text-muted-foreground">
          {a("navigationPreviewError")}
        </p>
      )}
      <AppearanceEditor
        value={appearance}
        onChange={setAppearance}
        onSave={() => void saveAppearance()}
        onReload={() => setReloadAppearance((value) => value + 1)}
        busy={appearanceBusy}
        dirty={appearanceDirty}
        problem={appearanceProblem}
      />
    </>
  );
  function changeOpen(next: boolean) {
    if (!next && (exitState.busy || appearanceBusy)) return;
    if (!next && (exitState.dirty || appearanceDirty)) {
      setConfirmExit({ close: true });
      return;
    }
    setOpen(next);
  }
  // The site's look belongs to the site, not the page: it survives a switch.
  function switchPage(pageId: string) {
    if (pageId === page.id || exitState.busy || !onSelectPage) return;
    if (exitState.dirty) {
      setConfirmExit({ pageId });
      return;
    }
    setExitState({ dirty: false, busy: true });
    onSelectPage(pageId);
  }
  // Menu order first (a child under its parent), then pages outside the menu.
  const orderedPages = useMemo(() => {
    const byId = new Map(pages.map((item) => [item.id, item]));
    const listed = menuOrder.flatMap((item) => {
      const found = byId.get(item.page_id);
      return found
        ? [{ page: found, nested: Boolean(item.parent_page_id) }]
        : [];
    });
    const seen = new Set(listed.map((item) => item.page.id));
    return [
      ...listed,
      ...pages
        .filter((item) => !seen.has(item.id))
        .map((item) => ({ page: item, nested: false })),
    ];
  }, [pages, menuOrder]);
  const pagesPanel =
    onSelectPage && pages.length > 1 ? (
      <>
        <p className="mb-4 text-sm text-muted-foreground">{t("pagesHint")}</p>
        <ul className="studio-outline">
          {orderedPages.map(({ page: item, nested }) => (
            <li key={item.id} className={nested ? "pl-4" : undefined}>
              <button
                type="button"
                aria-current={item.id === page.id ? "page" : undefined}
                disabled={exitState.busy && item.id !== page.id}
                onClick={() => switchPage(item.id)}
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">
                    {item.name}
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {item.key}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </>
    ) : undefined;
  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <DialogTrigger render={<Button type="button" />}>
        {t("openStudio")}
      </DialogTrigger>
      <DialogContent
        fullScreen
        showCloseButton={false}
        className="flex flex-col gap-0 overflow-hidden"
      >
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b bg-background px-4 py-3 sm:px-6">
          <div className="min-w-0">
            <DialogTitle className="truncate">
              {t("studioTitle", { page: page.name })}
            </DialogTitle>
            <DialogDescription className="sr-only">
              {t("studioDescription")}
            </DialogDescription>
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={exitState.busy || appearanceBusy}
            onClick={() => changeOpen(false)}
          >
            {t("backToPages")}
          </Button>
        </header>
        <div
          className="min-h-0 flex-1 overflow-hidden"
          data-testid="fullscreen-studio"
        >
          {open && (
            <PageEditor
              key={page.id}
              page={page}
              pagesPanel={pagesPanel}
              onChanged={onChanged}
              onExitStateChange={setExitState}
              navigation={navigation}
              appearance={previewAppearance}
              savedAppearance={savedAppearance?.data}
              appearanceControls={appearanceControls}
            />
          )}
        </div>
        <Dialog
          open={Boolean(confirmExit)}
          onOpenChange={(next) => {
            if (!next) setConfirmExit(false);
          }}
        >
          <DialogContent>
            <DialogTitle>{t("unsavedTitle")}</DialogTitle>
            <DialogDescription>
              {confirmExit && "pageId" in confirmExit
                ? t("unsavedSwitchDescription")
                : t("unsavedDescription")}
            </DialogDescription>
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                autoFocus
                type="button"
                variant="outline"
                onClick={() => setConfirmExit(false)}
              >
                {t("keepEditing")}
              </Button>
              <Button
                type="button"
                variant="destructive"
                onClick={() => {
                  const pending = confirmExit;
                  setConfirmExit(false);
                  setExitState({ dirty: false, busy: true });
                  if (pending && "pageId" in pending) {
                    onSelectPage?.(pending.pageId);
                    return;
                  }
                  setOpen(false);
                  setAppearance(savedAppearance?.data);
                  setAppearanceProblem(undefined);
                }}
              >
                {confirmExit && "pageId" in confirmExit
                  ? t("discardAndSwitch")
                  : t("discardChanges")}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </DialogContent>
    </Dialog>
  );
}
