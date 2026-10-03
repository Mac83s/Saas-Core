"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiProblemError,
  getProfileTranslations,
  updateProfileTranslation,
  type ProfileTranslation,
  type ProfileTranslationList,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@saas-core/ui/components/tabs";

import { Link } from "#i18n/navigation";
import { TranslateMissing } from "../translation/translate-missing";
import { TranslationFields } from "../translation/translation-fields";

const SOURCE_KEY = "profiles.public_profile";

function texts(language: ProfileTranslation): Record<string, string> {
  return Object.fromEntries(
    language.units.map((unit) => [unit.key, unit.text]),
  );
}

/**
 * „Inne języki” of the business card (TL12d): its headline, bio and link
 * labels in each other language of the company, next to the card they
 * translate, saved at the version they were read.
 */
export function ProfileTranslations({
  profileId,
  canManage,
}: {
  profileId: string;
  canManage: boolean;
}) {
  const t = useTranslations("Translations");
  const [list, setList] = useState<ProfileTranslationList>();
  const [locale, setLocale] = useState<string>();
  const [values, setValues] = useState<Record<string, Record<string, string>>>(
    {},
  );
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{
    text: string;
    tone: "ok" | "problem";
  }>();

  const load = useCallback(async () => {
    const answer = await getProfileTranslations(profileId);
    setList(answer);
    setValues(
      Object.fromEntries(answer.languages.map((l) => [l.locale, texts(l)])),
    );
    setLocale((chosen) => chosen ?? answer.languages[0]?.locale);
  }, [profileId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    load().catch(() => setMessage({ text: t("loadFailed"), tone: "problem" }));
  }, [load, t]);

  if (!list) return null;
  const language = list.languages.find((entry) => entry.locale === locale);

  function labelFor(key: string, entry: ProfileTranslation): string {
    if (key === "headline") return t("fieldHeadline");
    if (key === "bio") return t("fieldBio");
    const source =
      entry.units.find((unit) => unit.key === key)?.source_text ?? "";
    return t("fieldLinkLabel", { label: source });
  }

  async function save(entry: ProfileTranslation) {
    setBusy(true);
    setMessage(undefined);
    const current = values[entry.locale] ?? {};
    const linkLabels = Object.fromEntries(
      Object.entries(current).filter(([key]) => key.startsWith("link/")),
    );
    try {
      await updateProfileTranslation(profileId, entry.locale, {
        expected_version: entry.version,
        ...("headline" in current ? { headline: current.headline } : {}),
        ...("bio" in current ? { bio: current.bio } : {}),
        ...(Object.keys(linkLabels).length ? { link_labels: linkLabels } : {}),
      });
      await load();
      setMessage({ text: t("saved"), tone: "ok" });
    } catch (error) {
      const code =
        error instanceof ApiProblemError ? error.problem.code : undefined;
      setMessage({
        text:
          code === "profile_version_conflict"
            ? t("changedMeanwhile")
            : t("saveFailed"),
        tone: "problem",
      });
    } finally {
      setBusy(false);
    }
  }

  const form = (entry: ProfileTranslation) => (
    <TranslationFields
      disabled={!canManage || busy}
      idPrefix={`profile-${entry.locale}`}
      labelFor={(key) => labelFor(key, entry)}
      multiline={(key) => key === "bio"}
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
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{t("cardTitle")}</h2>
        </CardTitle>
        <CardDescription>{t("cardDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {list.languages.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("noOtherLanguages")}{" "}
            {canManage ? (
              <Link
                className="font-medium text-primary hover:underline"
                href="/panel/settings/languages"
              >
                {t("languagesLink")}
              </Link>
            ) : null}
          </p>
        ) : (
          <>
            {canManage ? (
              <TranslateMissing
                disabled={busy}
                onOrdered={() => void load()}
                targets={list.languages.map((entry) => ({
                  source_key: SOURCE_KEY,
                  object_id: profileId,
                  locale: entry.locale,
                  basis: "published",
                }))}
              />
            ) : null}
            {list.languages.length > 1 ? (
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
          </>
        )}
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
      </CardContent>
      {canManage && language ? (
        <CardFooter>
          <Button disabled={busy} onClick={() => void save(language)}>
            {t("save")}
          </Button>
        </CardFooter>
      ) : null}
    </Card>
  );
}
