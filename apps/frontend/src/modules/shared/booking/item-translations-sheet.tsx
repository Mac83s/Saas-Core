"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiProblemError,
  getBookingItemTranslations,
  previewBookingItemTranslation,
  updateBookingItemTranslation,
  type BookingItemKind,
  type BookingItemTranslation,
  type BookingItemTranslationList,
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
import {
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@saas-core/ui/components/tabs";

import { Link } from "#i18n/navigation";
import { TranslationFields } from "../translation/translation-fields";

export type TranslatedItem = {
  kind: BookingItemKind;
  id: string;
  name: string;
};

function texts(language: BookingItemTranslation): Record<string, string> {
  return Object.fromEntries(
    language.units.map((unit) => [unit.key, unit.text]),
  );
}

/**
 * „Tłumaczenia” of one item of Usługi i grafik (TL12d): its name (and
 * description) in each other language of the company, one language at a time,
 * saved at the version it was read (409: somebody changed it meanwhile).
 */
export function ItemTranslationsSheet({
  item,
  onClose,
}: {
  item?: TranslatedItem;
  onClose: () => void;
}) {
  const t = useTranslations("Translations");
  const [list, setList] = useState<BookingItemTranslationList>();
  const [locale, setLocale] = useState<string>();
  const [values, setValues] = useState<Record<string, Record<string, string>>>(
    {},
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{
    text: string;
    tone: "ok" | "problem";
  }>();

  const load = useCallback(async (current: TranslatedItem) => {
    const answer = await getBookingItemTranslations(current.kind, current.id);
    setList(answer);
    setValues(
      Object.fromEntries(answer.languages.map((l) => [l.locale, texts(l)])),
    );
    setLocale((chosen) => chosen ?? answer.languages[0]?.locale);
  }, []);

  useEffect(() => {
    if (!item) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a new item starts clean
    setList(undefined);
    setLocale(undefined);
    setMessage(undefined);
    load(item).catch(() =>
      setMessage({ text: t("loadFailed"), tone: "problem" }),
    );
  }, [item, load, t]);

  const language = list?.languages.find((entry) => entry.locale === locale);

  async function send(preview: boolean) {
    if (!item || !language) return;
    setBusy(true);
    setMessage(undefined);
    const input = {
      texts: values[language.locale] ?? {},
      expected_version: language.version,
    };
    try {
      if (preview) {
        await previewBookingItemTranslation(
          item.kind,
          item.id,
          language.locale,
          input,
        );
        setMessage({ text: t("previewOk"), tone: "ok" });
      } else {
        await updateBookingItemTranslation(
          item.kind,
          item.id,
          language.locale,
          input,
          crypto.randomUUID(),
        );
        await load(item);
        setMessage({ text: t("saved"), tone: "ok" });
      }
    } catch (error) {
      const code =
        error instanceof ApiProblemError ? error.problem.code : undefined;
      setMessage({
        text:
          code === "booking_version_conflict"
            ? t("changedMeanwhile")
            : t("saveFailed"),
        tone: "problem",
      });
    } finally {
      setBusy(false);
    }
  }

  const form = (entry: BookingItemTranslation) => (
    <TranslationFields
      disabled={busy}
      idPrefix={`item-${entry.locale}`}
      labelFor={(key) =>
        t(key === "description" ? "fieldDescription" : "fieldName")
      }
      multiline={(key) => key === "description"}
      onChange={(key, text) =>
        setValues((all) => ({
          ...all,
          [entry.locale]: { ...all[entry.locale], [key]: text },
        }))
      }
      units={entry.units}
      values={values[entry.locale] ?? {}}
    />
  );

  return (
    <Sheet
      onOpenChange={(open) => (open ? null : onClose())}
      open={item !== undefined}
    >
      <SheetContent closeLabel={t("close")}>
        <SheetHeader>
          <SheetTitle>{t("itemTitle", { name: item?.name ?? "" })}</SheetTitle>
          <SheetDescription>{t("itemDescription")}</SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-4">
          {list && list.languages.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("noOtherLanguages")}{" "}
              <Link
                className="font-medium text-primary hover:underline"
                href="/panel/settings/languages"
              >
                {t("languagesLink")}
              </Link>
            </p>
          ) : null}
          {list && list.languages.length > 1 ? (
            <Tabs
              onValueChange={(value) => setLocale(String(value))}
              value={locale}
            >
              <TabsList>
                {list.languages.map((entry) => (
                  <TabsTab key={entry.locale} value={entry.locale}>
                    {entry.locale.toUpperCase()}
                  </TabsTab>
                ))}
              </TabsList>
              {list.languages.map((entry) => (
                <TabsPanel key={entry.locale} value={entry.locale}>
                  {form(entry)}
                </TabsPanel>
              ))}
            </Tabs>
          ) : language ? (
            <>
              <p className="text-sm font-medium">
                {t("inLanguage", { locale: language.locale.toUpperCase() })}
              </p>
              {form(language)}
            </>
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
        {language ? (
          <SheetFooter>
            <Button
              disabled={busy}
              onClick={() => void send(true)}
              variant="outline"
            >
              {t("preview")}
            </Button>
            <Button disabled={busy} onClick={() => void send(false)}>
              {t("save")}
            </Button>
          </SheetFooter>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
