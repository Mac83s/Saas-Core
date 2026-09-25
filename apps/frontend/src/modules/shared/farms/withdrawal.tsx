"use client";

import { useFormatter, useTranslations } from "next-intl";

import { Badge } from "@saas-core/ui/components/badge";

/**
 * A medicine's withdrawal: until when milk and meat of the animal may not be
 * sold (decision of 25.09). On a list and a card it is a red badge while it
 * runs; in the history it is the line of the entry that set it.
 */
export function Withdrawal({
  milk,
  meat,
  plain = false,
}: {
  milk?: string | null;
  meat?: string | null;
  /** The history's line instead of the badge. */
  plain?: boolean;
}) {
  const t = useTranslations("Animals");
  const format = useFormatter();
  if (!milk && !meat) return null;
  const at = (iso: string) =>
    format.dateTime(new Date(iso), {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  const text = t("withdrawal", {
    parts: [
      milk ? t("withdrawalMilk", { until: at(milk) }) : null,
      meat ? t("withdrawalMeat", { until: at(meat) }) : null,
    ]
      .filter(Boolean)
      .join(" · "),
  });
  if (plain) return <p className="mt-1 text-sm font-medium">{text}</p>;
  return (
    <Badge className="h-auto whitespace-normal" variant="destructive">
      {text}
    </Badge>
  );
}
