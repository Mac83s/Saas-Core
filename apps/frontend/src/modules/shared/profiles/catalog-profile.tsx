import { getTranslations } from "next-intl/server";

import type { CatalogProfile } from "@saas-core/api-client";

/**
 * One catalogue page, rendered from a record rather than from blocks.
 *
 * ADR-053 §6: this is not a second publication path — sites keep theirs
 * untouched. The layout is a closed choice on the profile, so a company picks
 * a shape without the platform growing an editor it does not need.
 */
export async function CatalogProfilePage({
  profile,
}: {
  profile: CatalogProfile;
}) {
  const t = await getTranslations("Catalog");
  const cover = profile.layout === "cover";
  const compact = profile.layout === "compact";

  return (
    <article className="space-y-8">
      <header
        className={
          cover ? "bg-muted rounded-lg px-6 py-12 text-center" : "space-y-2"
        }
      >
        <h1 className="text-3xl font-semibold tracking-tight">
          {profile.display_name}
        </h1>
        {profile.headline && (
          <p className="text-muted-foreground text-lg">{profile.headline}</p>
        )}
        <p className="text-muted-foreground text-sm">
          {profile.city}
          {profile.voivodeship ? `, ${profile.voivodeship}` : ""}
        </p>
      </header>

      {profile.bio && !compact && (
        <section className="max-w-prose whitespace-pre-line leading-relaxed">
          {profile.bio}
        </section>
      )}

      {profile.specializations.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-medium">{t("specializations")}</h2>
          <ul className="flex flex-wrap gap-2">
            {profile.specializations.map((key) => (
              <li className="bg-muted rounded-full px-3 py-1 text-sm" key={key}>
                {key}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="space-y-1">
        <h2 className="mb-2 text-sm font-medium">{t("contact")}</h2>
        {profile.contact_phone && (
          <p>
            <a className="underline" href={`tel:${profile.contact_phone}`}>
              {profile.contact_phone}
            </a>
          </p>
        )}
        {profile.contact_email && (
          <p>
            <a className="underline" href={`mailto:${profile.contact_email}`}>
              {profile.contact_email}
            </a>
          </p>
        )}
        {profile.contact_address && (
          <p className="text-muted-foreground">{profile.contact_address}</p>
        )}
      </section>

      {profile.links.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-medium">{t("links")}</h2>
          <ul className="space-y-1">
            {profile.links.map((link) => (
              <li key={String(link.url)}>
                <a
                  className="underline"
                  href={String(link.url)}
                  rel="noreferrer nofollow"
                  target="_blank"
                >
                  {String(link.label)}
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}

      {profile.is_external && (
        <p>
          <a className="underline" href={profile.url} rel="noreferrer">
            {t("visitSite")}
          </a>
        </p>
      )}
    </article>
  );
}
