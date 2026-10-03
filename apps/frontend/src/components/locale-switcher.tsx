"use client";

import { useLocale, useTranslations } from "next-intl";

import { usePathname, useRouter } from "#i18n/navigation";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@saas-core/ui/components/select";

export function LocaleSwitcher() {
  const locale = useLocale();
  const t = useTranslations("Panel");
  const common = useTranslations("Common");
  const pathname = usePathname();
  const router = useRouter();

  return (
    <Select
      onValueChange={(nextLocale) => {
        if (nextLocale === "pl" || nextLocale === "en") {
          router.replace(pathname, { locale: nextLocale });
        }
      }}
      // A guest language (TL17) is not one of the panel's two; switching from
      // it keeps the address.
      value={locale === "pl" || locale === "en" ? locale : undefined}
    >
      <SelectTrigger aria-label={t("language")} size="sm">
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="end">
        <SelectItem value="pl">{common("polish")}</SelectItem>
        <SelectItem value="en">{common("english")}</SelectItem>
      </SelectContent>
    </Select>
  );
}
