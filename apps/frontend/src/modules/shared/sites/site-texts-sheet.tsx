"use client";

/** „Nagłówek i stopka” in one other language (TL16g): the site's own texts —
 *  the tagline, the footer and its link labels, blog and tag names — each
 *  beside its source, saved at the version it was read and put on the site
 *  with the next publication or at once with „Opublikuj teraz”. A text an
 *  automatic translation left for a person to decide is shown under its
 *  field; the decision itself is taken in „Do akceptacji”. */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiProblemError,
  getSiteTexts,
  publishSiteTexts,
  saveSiteTexts,
  type SiteTexts,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Sheet,
  SheetBody,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@saas-core/ui/components/sheet";

import { nativeName } from "#lib/company-locales";
import { TranslationFields } from "../translation/translation-fields";

type Item = SiteTexts["items"][number];

const values = (texts: SiteTexts): Record<string, string> =>
  Object.fromEntries(texts.items.map((item) => [item.key, item.text]));

export function SiteTextsSheet({
  siteId,
  locale,
  onClose,
  onChanged,
}: {
  siteId: string;
  /** The language being translated into; nothing while the sheet is closed. */
  locale: string | undefined;
  onClose: () => void;
  /** A save or a publication changed what the overview shows. */
  onChanged: () => void;
}) {
  const t = useTranslations("Sites.translationsCentre.siteTexts");
  const fields = useTranslations("Translations");
  // The texts as read, with the language they are in: another language's
  // answer is not this one's.
  const [read, setRead] = useState<{ locale: string; texts: SiteTexts }>();
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{
    text: string;
    tone: "ok" | "problem";
  }>();

  const load = useCallback(
    async (language: string) => {
      const texts = await getSiteTexts(siteId, language);
      setRead({ locale: language, texts });
      setEdited(values(texts));
    },
    [siteId],
  );

  useEffect(() => {
    if (!locale) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- another language starts clean
    setMessage(undefined);
    load(locale).catch(() =>
      setMessage({ text: t("loadFailed"), tone: "problem" }),
    );
  }, [locale, load, t]);

  const texts = read && read.locale === locale ? read.texts : undefined;
  const items = texts?.items ?? [];
  const byKey = new Map<string, Item>(items.map((item) => [item.key, item]));
  const changed = Object.fromEntries(
    items
      .filter((item) => (edited[item.key] ?? "").trim() !== item.text)
      .map((item) => [item.key, edited[item.key] ?? ""]),
  );
  const dirty = Object.keys(changed).length > 0;

  const labelFor = (key: string) => {
    const item = byKey.get(key);
    return item ? t(`roles.${item.role}`, { text: item.source_text }) : key;
  };

  async function save() {
    if (!locale || !texts || !dirty) return;
    setBusy(true);
    setMessage(undefined);
    try {
      const saved = await saveSiteTexts(siteId, locale, {
        expected_version: texts.version,
        texts: changed,
      });
      setRead({ locale, texts: saved });
      setEdited(values(saved));
      setMessage({ text: t("saved"), tone: "ok" });
      onChanged();
    } catch (error) {
      const problem =
        error instanceof ApiProblemError ? error.problem : undefined;
      if (problem?.code === "site_texts_version_conflict") {
        // Somebody saved meanwhile: show theirs, keep nothing of ours unsaid.
        await load(locale).catch(() => undefined);
        setMessage({ text: t("conflict"), tone: "problem" });
      } else {
        const named = problem?.errors?.[0];
        const item = named
          ? byKey.get(named.field.replace(/^texts\./, ""))
          : undefined;
        setMessage({
          text:
            named && item
              ? t("fieldProblem", {
                  field: t(`roles.${item.role}`, { text: item.source_text }),
                  message: named.message,
                })
              : t("saveFailed"),
          tone: "problem",
        });
      }
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    if (!locale) return;
    setBusy(true);
    setMessage(undefined);
    try {
      await publishSiteTexts(siteId, locale, crypto.randomUUID());
      setMessage({ text: t("published"), tone: "ok" });
      onChanged();
    } catch (error) {
      const status =
        error instanceof ApiProblemError ? error.problem.status : undefined;
      setMessage({
        text: t(
          status === 403
            ? "publishForbidden"
            : status === 409
              ? "publishNotReady"
              : "publishFailed",
        ),
        tone: "problem",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet
      onOpenChange={(open) => (open || busy ? null : onClose())}
      open={locale !== undefined}
    >
      <SheetContent closeLabel={fields("close")}>
        <SheetHeader>
          <SheetTitle>
            {t("title", { language: locale ? nativeName(locale) : "" })}
          </SheetTitle>
          <SheetDescription>{t("description")}</SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-4">
          {texts && items.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("empty")}</p>
          ) : null}
          {texts && items.length > 0 ? (
            <TranslationFields
              disabled={busy}
              idPrefix={`site-texts-${locale}`}
              labelFor={labelFor}
              multiline={(key) => byKey.get(key)?.role === "footer"}
              noteFor={(key) => {
                const waiting = byKey.get(key)?.pending_text;
                return waiting ? (
                  <p className="text-xs text-muted-foreground wrap-anywhere">
                    {t("pending", { text: waiting })}
                  </p>
                ) : null;
              }}
              onChange={(key, text) =>
                setEdited((all) => ({ ...all, [key]: text }))
              }
              units={items.map((item) => ({
                key: item.key,
                source_text: item.source_text,
                text: item.text,
                status: item.state,
                origin: item.origin,
              }))}
              values={edited}
            />
          ) : null}
          {message ? (
            <p
              className={
                message.tone === "ok"
                  ? "text-sm text-success-foreground"
                  : "text-sm text-destructive"
              }
              role={message.tone === "ok" ? "status" : "alert"}
            >
              {message.text}
            </p>
          ) : null}
        </SheetBody>
        {texts && items.length > 0 ? (
          <SheetFooter>
            <Button
              disabled={busy || dirty}
              onClick={() => void publish()}
              title={dirty ? t("saveFirst") : undefined}
              type="button"
              variant="outline"
            >
              {t("publish")}
            </Button>
            <Button
              disabled={busy || !dirty}
              onClick={() => void save()}
              type="button"
            >
              {t("save")}
            </Button>
          </SheetFooter>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
