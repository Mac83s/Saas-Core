"use client";

import { useId, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { XIcon } from "lucide-react";
import {
  deadAnchorLinks,
  sampleData,
  unfilledPlaceholders,
} from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import { cn } from "@saas-core/ui/lib/utils";

import { blockOptions, type BlockFormValues } from "./block-form";
import { outlineTitle, UnfilledBadge } from "./section-canvas";

/** How many `[Uzupełnij: …]` markers each section still holds, by position. */
export function unfilledBySection(blocks: readonly BlockFormValues[]) {
  const counts = blocks.map(() => 0);
  for (const { blockIndex } of unfilledPlaceholders(blocks))
    counts[blockIndex] += 1;
  return counts;
}

/** What else is left from a template (F4-P1): demonstration contact data and
 *  in-page links to a section the page does not have. */
export function templateLeftovers(blocks: readonly BlockFormValues[]) {
  return {
    samples: sampleData(blocks),
    deadAnchors: deadAnchorLinks(blocks),
  };
}

/** Guidance, not a gate: templates leave places for the owner's real proof,
 *  sample contact data and links to sections a page may lack, and the banner
 *  says where they still are. Saving and publishing stay open. */
export function PlaceholderBanner({
  blocks,
  counts,
  leftovers = { samples: [], deadAnchors: [] },
  onChoose,
}: {
  blocks: readonly BlockFormValues[];
  counts: readonly number[];
  leftovers?: ReturnType<typeof templateLeftovers>;
  onChoose: (index: number) => void;
}) {
  const t = useTranslations("Sites");
  const detailsId = useId();
  // A phone shows one line until asked; anyone may close it for now — it
  // comes back with the next opening of the page (UX-039).
  const [expanded, setExpanded] = useState(false);
  const [closed, setClosed] = useState(false);
  const total = counts.reduce((sum, count) => sum + count, 0);
  const { samples, deadAnchors } = leftovers;
  if (closed || (!total && !samples.length && !deadAnchors.length)) return null;
  const short = [
    total ? t("studio.placeholders.count", { count: total }) : null,
    samples.length ? t("studio.leftovers.samplesShort") : null,
    deadAnchors.length
      ? t("studio.leftovers.deadAnchorsShort", { count: deadAnchors.length })
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const title = (index: number) =>
    outlineTitle(blocks[index]) ||
    t(
      blockOptions.find((option) => option.type === blocks[index].block_type)
        ?.labelKey ?? "addBlock",
    );
  const sectionButtons = (
    label: string,
    sections: readonly number[],
    detail: (index: number) => ReactNode,
  ) => (
    <ul aria-label={label} className="mt-2 flex flex-wrap gap-2">
      {sections.map((index) => (
        // A long section name truncates inside the screen (UX-039).
        <li className="max-w-full min-w-0" key={index}>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-auto min-h-8 max-w-full bg-background"
            onClick={() => onChoose(index)}
          >
            <span className="min-w-0 truncate">
              {index + 1}. {title(index)}
            </span>{" "}
            {detail(index)}
          </Button>
        </li>
      ))}
    </ul>
  );
  const sections = counts.flatMap((count, index) => (count ? [index] : []));
  const list = sectionButtons(
    t("studio.placeholders.sections"),
    sections,
    (index) => <UnfilledBadge count={counts[index]} />,
  );
  const unique = (values: readonly string[]) => [...new Set(values)];
  const where = (found: readonly { blockIndex: number }[]) =>
    unique(found.map((item) => String(item.blockIndex))).map(Number);
  return (
    <div className="flex shrink-0 flex-wrap items-start gap-x-2 gap-y-3 border-b border-warning-foreground/30 bg-warning px-4 py-3 text-sm text-warning-foreground">
      <p className="min-w-0 flex-1 self-center font-medium sm:hidden">
        {short}
      </p>
      <Button
        aria-controls={detailsId}
        aria-expanded={expanded}
        className="sm:hidden"
        onClick={() => setExpanded(!expanded)}
        size="sm"
        type="button"
        variant="ghost"
      >
        {expanded ? t("studio.banner.less") : t("studio.banner.more")}
      </Button>
      <div
        className={cn(
          "min-w-0 space-y-3 max-sm:order-last max-sm:basis-full sm:flex-1",
          !expanded && "max-sm:hidden",
        )}
        id={detailsId}
      >
        {total ? (
          <div>
            <p role="status" className="font-medium">
              {t("studio.placeholders.summary", { count: total })}
            </p>
            <p>{t("studio.placeholders.hint", { count: total })}</p>
            {sections.length > 3 ? (
              <details className="mt-1">
                <summary className="cursor-pointer font-medium">
                  {t("studio.placeholders.showSections", {
                    count: sections.length,
                  })}
                </summary>
                {list}
              </details>
            ) : (
              list
            )}
          </div>
        ) : null}
        {samples.length ? (
          <div>
            <p role="status" className="font-medium">
              {t("studio.leftovers.samples", {
                values: unique(samples.map((sample) => sample.text)).join(", "),
              })}
            </p>
            <p>{t("studio.leftovers.samplesHint")}</p>
            {/* Each chip says what is in its section, so a section that also
              holds slots does not look like the same chip twice (UX-038). */}
            {sectionButtons(
              t("studio.leftovers.samplesSections"),
              where(samples),
              (index) => (
                <span className="text-xs text-muted-foreground">
                  {t("studio.leftovers.sampleChip", {
                    values: unique(
                      samples
                        .filter((sample) => sample.blockIndex === index)
                        .map((sample) => sample.text),
                    ).join(", "),
                  })}
                </span>
              ),
            )}
          </div>
        ) : null}
        {deadAnchors.length ? (
          <div>
            <p role="status" className="font-medium">
              {t("studio.leftovers.deadAnchors", {
                count: deadAnchors.length,
                anchors: unique(deadAnchors.map((link) => link.href)).join(
                  ", ",
                ),
              })}
            </p>
            <p>{t("studio.leftovers.deadAnchorsHint")}</p>
            {sectionButtons(
              t("studio.leftovers.deadAnchorsSections"),
              where(deadAnchors),
              (index) => (
                <span className="text-xs text-muted-foreground">
                  {unique(
                    deadAnchors
                      .filter((link) => link.blockIndex === index)
                      .map((link) => link.href),
                  ).join(", ")}
                </span>
              ),
            )}
          </div>
        ) : null}
      </div>
      <Button
        aria-label={t("studio.banner.close")}
        onClick={() => setClosed(true)}
        size="icon"
        title={t("studio.banner.close")}
        type="button"
        variant="ghost"
      >
        <XIcon aria-hidden="true" />
      </Button>
    </div>
  );
}
