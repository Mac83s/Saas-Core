"use client";

import type { ReactNode, RefObject } from "react";
import { useTranslations } from "next-intl";
import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react";
import { Button } from "@saas-core/ui/components/button";

/**
 * „Dziś”, the arrows and the range they move over, in one row on a phone too
 * (UX-026): the calendar's views and „Obłożenie” move through time the same
 * way. The range is the region's heading, read out when it changes and
 * focused when a dialog's opener is gone.
 */
export function CalendarNav({
  headingId,
  headingRef,
  heading,
  previousLabel,
  nextLabel,
  onToday,
  onPrevious,
  onNext,
  todayDisabled = false,
}: {
  headingId: string;
  headingRef?: RefObject<HTMLHeadingElement | null>;
  heading: ReactNode;
  previousLabel: string;
  nextLabel: string;
  onToday: () => void;
  onPrevious: () => void;
  onNext: () => void;
  /** The range already holds today. */
  todayDisabled?: boolean;
}) {
  const t = useTranslations("Calendar");
  return (
    <div className="flex min-w-0 items-center gap-2">
      <Button disabled={todayDisabled} onClick={onToday} variant="outline">
        {t("today")}
      </Button>
      <Button
        aria-label={previousLabel}
        onClick={onPrevious}
        size="icon"
        variant="outline"
      >
        <ChevronLeftIcon aria-hidden="true" />
      </Button>
      <Button
        aria-label={nextLabel}
        onClick={onNext}
        size="icon"
        variant="outline"
      >
        <ChevronRightIcon aria-hidden="true" />
      </Button>
      <h2
        aria-live="polite"
        className="ml-1 min-w-0 text-base font-semibold outline-none first-letter:uppercase sm:text-xl"
        id={headingId}
        ref={headingRef}
        tabIndex={-1}
      >
        {heading}
      </h2>
    </div>
  );
}
