"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronLeftIcon } from "lucide-react";
import {
  getSiteAppearance,
  getSiteNavigation,
  getSiteLocalizationReport,
  saveSiteAppearance,
  type PageSummary,
  type SiteLocalizationReport,
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
import { useCompanyLocales } from "#lib/company-locales";
import { LanguageSwitch, pageLanguageOptions } from "./language-switch";
import { PageEditor } from "./page-editor";
import { PageLanguageEditor } from "./page-language-editor";

/** The language the editor shows, kept in the address (`?language=de`) so a
 *  refresh or a shared link opens the same one (TL15). */
function addressLanguage(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("language");
}

function keepLanguageInAddress(locale: string | null) {
  const url = new URL(window.location.href);
  if (locale) url.searchParams.set("language", locale);
  else url.searchParams.delete("language");
  window.history.replaceState(window.history.state, "", url);
}

export function PageStudio({
  page,
  pages = [],
  onChanged,
  onSelectPage,
  previewOnOpen = false,
  onClose,
}: {
  page: PageSummary;
  /** The site's pages: with `onSelectPage`, the studio switches between them
   *  without closing (F3-Z3). */
  pages?: readonly PageSummary[];
  onChanged: () => Promise<void>;
  onSelectPage?: (pageId: string) => void;
  /** Opens the page's preview as soon as the draft is loaded. */
  previewOnOpen?: boolean;
  /** The studio was closed: a caller that opened it from its list goes back. */
  onClose?: () => void;
}) {
  const t = useTranslations("Sites.studio");
  const [open, setOpen] = useState(true);
  const close = () => {
    setOpen(false);
    onClose?.();
  };
  // What waits for "Odrzuć zmiany": closing the studio, another page or
  // another language.
  const [confirmExit, setConfirmExit] = useState<
    false | { close: true } | { pageId: string } | { locale: string }
  >(false);
  const [report, setReport] = useState<SiteLocalizationReport>();
  const [reloadReport, setReloadReport] = useState(0);
  const companyLocales = useCompanyLocales(["pl", "en"]);
  const [requestedLanguage, setRequestedLanguage] = useState<string | null>(
    addressLanguage,
  );
  const languages = useMemo(
    () => pageLanguageOptions(report, page.id, companyLocales),
    [report, page.id, companyLocales],
  );
  const sourceLocale = report?.default_locale ?? languages[0]?.locale ?? "pl";
  // A language the company no longer has, or the source by its code, is
  // the source.
  const contentLocale =
    requestedLanguage &&
    requestedLanguage !== sourceLocale &&
    languages.some((item) => item.locale === requestedLanguage)
      ? requestedLanguage
      : sourceLocale;
  const nameOf = (code: string) =>
    languages.find((item) => item.locale === code)?.name ?? code.toUpperCase();
  function chooseLanguage(locale: string) {
    if (locale === contentLocale || exitState.busy) return;
    if (exitState.dirty) {
      setConfirmExit({ locale });
      return;
    }
    applyLanguage(locale);
  }
  function applyLanguage(locale: string) {
    const next = locale === sourceLocale ? null : locale;
    setRequestedLanguage(next);
    keepLanguageInAddress(next);
    setExitState({ dirty: false, busy: false });
  }
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
        setReport(report);
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
  }, [open, page.site_id, reloadReport]);
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
    if (next) setOpen(true);
    else close();
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
  // In the editor's toolbar, whichever language it shows (UX-039 slot).
  const languageSwitch = (
    <LanguageSwitch
      value={contentLocale}
      options={languages}
      onChange={chooseLanguage}
      disabled={exitState.busy}
    />
  );
  const editingSource = contentLocale === sourceLocale;
  const backButton = (compact: boolean) => (
    <Button
      type="button"
      variant="ghost"
      size={compact ? "icon-sm" : "default"}
      className={compact ? "pointer-fine:size-8" : "max-sm:px-2"}
      title={compact ? t("backToPages") : undefined}
      disabled={exitState.busy || appearanceBusy}
      onClick={() => changeOpen(false)}
    >
      <ChevronLeftIcon aria-hidden="true" />
      <span className={compact ? "sr-only" : "max-sm:sr-only"}>
        {t("backToPages")}
      </span>
    </Button>
  );
  const dialogDescription = (
    <DialogDescription className="sr-only">
      {t("studioDescription")}
    </DialogDescription>
  );
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
        {/* The source's editor puts the way back into its own top bar; a
            language version keeps this row: back first, then the page, on a
            phone one short row with save and „…” under it (UX-039). */}
        {!editingSource && (
          <header className="flex shrink-0 items-center gap-2 border-b bg-background px-4 py-2 sm:gap-3 sm:px-6 sm:py-3">
            {backButton(false)}
            <div className="min-w-0 flex-1">
              <DialogTitle className="truncate">
                {t("studioTitle", { page: page.name })}
              </DialogTitle>
              {dialogDescription}
            </div>
          </header>
        )}
        <div
          className="min-h-0 flex-1 overflow-hidden"
          data-testid="fullscreen-studio"
        >
          {open && !editingSource && (
            <PageLanguageEditor
              key={`${page.id}-${contentLocale}`}
              page={page}
              locale={contentLocale}
              languageName={nameOf(contentLocale)}
              sourceName={nameOf(sourceLocale)}
              languageSwitch={languageSwitch}
              appearance={savedAppearance?.data}
              onSwitchToSource={() => chooseLanguage(sourceLocale)}
              onChanged={() => {
                setReloadReport((value) => value + 1);
                void onChanged();
              }}
              onExitStateChange={setExitState}
            />
          )}
          {open && editingSource && (
            <PageEditor
              key={page.id}
              leading={
                <>
                  {backButton(true)}
                  {/* The bar shows the page's name; the dialog keeps its
                      full title for a screen reader. */}
                  <DialogTitle className="sr-only">
                    {t("studioTitle", { page: page.name })}
                  </DialogTitle>
                  {dialogDescription}
                </>
              }
              page={page}
              pagesPanel={pagesPanel}
              previewOnOpen={previewOnOpen}
              onChanged={onChanged}
              onExitStateChange={setExitState}
              navigation={navigation}
              appearance={previewAppearance}
              savedAppearance={savedAppearance?.data}
              appearanceControls={appearanceControls}
              languageSwitch={languageSwitch}
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
              {confirmExit &&
              ("pageId" in confirmExit || "locale" in confirmExit)
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
                  if (pending && "locale" in pending) {
                    applyLanguage(pending.locale);
                    return;
                  }
                  close();
                  setAppearance(savedAppearance?.data);
                  setAppearanceProblem(undefined);
                }}
              >
                {confirmExit &&
                ("pageId" in confirmExit || "locale" in confirmExit)
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
