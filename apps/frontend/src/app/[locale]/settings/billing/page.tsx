import { redirect } from "next/navigation";

export default async function LegacyBillingCallbackPage({
  params,
  searchParams,
}: {
  params: Promise<{ locale: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [{ locale }, values] = await Promise.all([params, searchParams]);
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (Array.isArray(value)) value.forEach((item) => query.append(key, item));
    else if (value !== undefined) query.set(key, value);
  }
  const destination =
    locale === "pl"
      ? "/panel/settings/billing"
      : `/${locale}/panel/settings/billing`;
  redirect(query.size ? `${destination}?${query.toString()}` : destination);
}
