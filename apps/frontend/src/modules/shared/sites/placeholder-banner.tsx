"use client";

import { useTranslations } from "next-intl";
import { unfilledPlaceholders } from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";

import { blockOptions, type BlockFormValues } from "./block-form";
import { outlineTitle, UnfilledBadge } from "./section-canvas";

/** How many `[Uzupełnij: …]` markers each section still holds, by position. */
export function unfilledBySection(blocks: readonly BlockFormValues[]) {
  const counts = blocks.map(() => 0);
  for (const { blockIndex } of unfilledPlaceholders(blocks))
    counts[blockIndex] += 1;
  return counts;
}

/** Guidance, not a gate: templates leave places for the owner's real proof,
 *  and the banner says where they still are. Saving and publishing stay open. */
export function PlaceholderBanner({
  blocks,
  counts,
  onChoose,
}: {
  blocks: readonly BlockFormValues[];
  counts: readonly number[];
  onChoose: (index: number) => void;
}) {
  const t = useTranslations("Sites");
  const total = counts.reduce((sum, count) => sum + count, 0);
  if (!total) return null;
  const sections = counts.flatMap((count, index) => (count ? [index] : []));
  const list = (
    <ul
      aria-label={t("studio.placeholders.sections")}
      className="mt-2 flex flex-wrap gap-2"
    >
      {sections.map((index) => (
        <li key={index}>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-auto min-h-8 max-w-full bg-background"
            onClick={() => onChoose(index)}
          >
            <span className="min-w-0 truncate">
              {index + 1}.{" "}
              {outlineTitle(blocks[index]) ||
                t(
                  blockOptions.find(
                    (option) => option.type === blocks[index].block_type,
                  )?.labelKey ?? "addBlock",
                )}
            </span>{" "}
            <UnfilledBadge count={counts[index]} />
          </Button>
        </li>
      ))}
    </ul>
  );
  return (
    <div className="shrink-0 border-b border-warning-foreground/30 bg-warning px-4 py-3 text-sm text-warning-foreground">
      <p role="status" className="font-medium">
        {t("studio.placeholders.summary", { count: total })}
      </p>
      <p>{t("studio.placeholders.hint", { count: total })}</p>
      {sections.length > 3 ? (
        <details className="mt-1">
          <summary className="cursor-pointer font-medium">
            {t("studio.placeholders.showSections", { count: sections.length })}
          </summary>
          {list}
        </details>
      ) : (
        list
      )}
    </div>
  );
}
