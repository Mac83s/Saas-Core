"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ExternalLinkIcon, LoaderCircleIcon } from "lucide-react";

import {
  publishOrganizationProfile,
  readCatalogDictionary,
  readOrganizationProfile,
  updateProfile,
  withdrawOrganizationProfile,
  type CatalogDictionary,
  type CatalogState,
  type PublicProfileSummary,
} from "@saas-core/api-client";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Switch } from "@saas-core/ui/components/switch";
import { Textarea } from "@saas-core/ui/components/textarea";

import { profileProblem } from "./problem";

/** The three catalogue page layouts (ADR-053 §6); the keys are the contract. */
const LAYOUTS = ["card", "cover", "compact"] as const;

type Layout = (typeof LAYOUTS)[number];

/**
 * The summary types `layout` as a plain string while the update wants the
 * union, so the narrowing happens once, here. An unknown value falls back to
 * the default rather than failing the save: the person is editing a phone
 * number, not a layout.
 */
function asLayout(value: string): Layout {
  return (LAYOUTS as readonly string[]).includes(value)
    ? (value as Layout)
    : "card";
}

type Loaded = {
  profile: PublicProfileSummary;
  catalog: CatalogState;
  dictionary: CatalogDictionary;
};

export function ProfilePanel({ canManage }: { canManage: boolean }) {
  const t = useTranslations("Profile");
  const [state, setState] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [body, dictionary] = await Promise.all([
          readOrganizationProfile(),
          readCatalogDictionary(),
        ]);
        if (!cancelled) {
          setState({ ...body, dictionary });
          setError(null);
        }
      } catch (caught) {
        if (!cancelled) setError(profileProblem(caught, t("loadFailed")));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  if (error && !state)
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>{t("title")}</h2>
          </CardTitle>
          <CardDescription>{error}</CardDescription>
        </CardHeader>
      </Card>
    );

  if (!state)
    return (
      <p className="text-muted-foreground flex items-center gap-2 text-sm">
        <LoaderCircleIcon aria-hidden="true" className="size-4 animate-spin" />
        {t("loading")}
      </p>
    );

  const { profile, catalog, dictionary } = state;

  async function save(values: Partial<PublicProfileSummary>) {
    setBusy(true);
    try {
      const saved = await updateProfile(profile.id, {
        display_name: values.display_name ?? profile.display_name,
        headline: values.headline ?? profile.headline,
        bio: values.bio ?? profile.bio,
        city_slug: values.city_slug ?? profile.city_slug,
        category: values.category ?? profile.category,
        layout: asLayout(values.layout ?? profile.layout),
        contact_email: values.contact_email ?? profile.contact_email,
        contact_phone: values.contact_phone ?? profile.contact_phone,
        contact_address: values.contact_address ?? profile.contact_address,
        expected_version: profile.version,
      });
      setState({ ...state!, profile: saved });
      setError(null);
    } catch (caught) {
      setError(profileProblem(caught, t("saveFailed")));
    } finally {
      setBusy(false);
    }
  }

  async function togglePublication() {
    setBusy(true);
    try {
      if (catalog.published) {
        await withdrawOrganizationProfile();
        const body = await readOrganizationProfile();
        setState({ ...state!, ...body });
      } else {
        const body = await publishOrganizationProfile();
        setState({ ...state!, ...body });
      }
      setError(null);
    } catch (caught) {
      setError(profileProblem(caught, t("publishFailed")));
    } finally {
      setBusy(false);
    }
  }

  const readOnly = !canManage || busy;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>{t("title")}</h2>
          </CardTitle>
          <CardDescription>{t("intro")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Field>
            <FieldLabel htmlFor="profile-name">{t("name")}</FieldLabel>
            <Input
              defaultValue={profile.display_name}
              disabled={readOnly}
              id="profile-name"
              onBlur={(event) =>
                void save({ display_name: event.target.value })
              }
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="profile-headline">{t("headline")}</FieldLabel>
            <Input
              defaultValue={profile.headline}
              disabled={readOnly}
              id="profile-headline"
              onBlur={(event) => void save({ headline: event.target.value })}
              placeholder={t("headlinePlaceholder")}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="profile-bio">{t("bio")}</FieldLabel>
            <Textarea
              defaultValue={profile.bio}
              disabled={readOnly}
              id="profile-bio"
              onBlur={(event) => void save({ bio: event.target.value })}
              rows={5}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field>
              <FieldLabel htmlFor="profile-city">{t("city")}</FieldLabel>
              <NativeSelect
                disabled={readOnly}
                id="profile-city"
                onChange={(event) =>
                  void save({ city_slug: event.target.value })
                }
                value={profile.city_slug}
              >
                <option value="">{t("choose")}</option>
                {dictionary.cities.map((city) => (
                  <option key={city.slug} value={city.slug}>
                    {city.name}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field>
              <FieldLabel htmlFor="profile-category">
                {t("category")}
              </FieldLabel>
              <NativeSelect
                disabled={readOnly}
                id="profile-category"
                onChange={(event) =>
                  void save({ category: event.target.value })
                }
                value={profile.category}
              >
                <option value="">{t("choose")}</option>
                {dictionary.categories.map((category) => (
                  <option key={category.key} value={category.key}>
                    {category.labels.pl ?? category.key}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field>
              <FieldLabel htmlFor="profile-phone">{t("phone")}</FieldLabel>
              <Input
                defaultValue={profile.contact_phone}
                disabled={readOnly}
                id="profile-phone"
                onBlur={(event) =>
                  void save({ contact_phone: event.target.value })
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="profile-email">{t("email")}</FieldLabel>
              <Input
                defaultValue={profile.contact_email}
                disabled={readOnly}
                id="profile-email"
                onBlur={(event) =>
                  void save({ contact_email: event.target.value })
                }
                type="email"
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="profile-address">{t("address")}</FieldLabel>
              <Input
                defaultValue={profile.contact_address}
                disabled={readOnly}
                id="profile-address"
                onBlur={(event) =>
                  void save({ contact_address: event.target.value })
                }
              />
            </Field>
          </div>
          <Field>
            <FieldLabel htmlFor="profile-layout">{t("layout")}</FieldLabel>
            <NativeSelect
              disabled={readOnly}
              id="profile-layout"
              onChange={(event) => void save({ layout: event.target.value })}
              value={profile.layout}
            >
              {LAYOUTS.map((layout) => (
                <option key={layout} value={layout}>
                  {t(`layout_${layout}`)}
                </option>
              ))}
            </NativeSelect>
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>{t("catalogTitle")}</h2>
          </CardTitle>
          <CardDescription>
            {catalog.published
              ? t("catalogPublished")
              : t("catalogNotPublished")}
          </CardDescription>
        </CardHeader>
        {catalog.published && (
          <CardContent className="space-y-2 text-sm">
            <p>
              <a
                className="text-primary inline-flex items-center gap-1 underline"
                href={catalog.site_url ?? catalog.path}
                rel="noreferrer"
                target="_blank"
              >
                {catalog.site_url ?? catalog.path}
                <ExternalLinkIcon aria-hidden="true" className="size-3.5" />
              </a>
            </p>
            {/* Which of the two the entry leads to, so nobody has to guess
                from the address (ADR-053 §5). */}
            <p className="text-muted-foreground">
              {catalog.site_url ? t("leadsToSite") : t("leadsToCatalog")}
            </p>
          </CardContent>
        )}
        <CardFooter className="flex-col items-start gap-3">
          {/* On/off rather than "publish": the card always exists (ADR-053),
              and not every company wants to be listed. */}
          <label className="flex min-h-11 items-center gap-3 font-medium">
            <Switch
              checked={catalog.published}
              disabled={readOnly}
              onCheckedChange={() => void togglePublication()}
            />
            {t("showInCatalog")}
          </label>
          {error && (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          )}
        </CardFooter>
      </Card>
    </div>
  );
}
