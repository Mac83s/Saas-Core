"use client";

import { Progress as ProgressPrimitive } from "@base-ui/react/progress";

import { cn } from "#lib/utils";

/** How far a piece of work has come, as a bar. Name it with `aria-label` or
 *  `aria-labelledby`; `value` runs from 0 to `max`, and `null` means the work
 *  goes on with nothing to measure yet. */
function Progress({ className, ...props }: ProgressPrimitive.Root.Props) {
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      className={cn("w-full", className)}
      {...props}
    >
      <ProgressPrimitive.Track
        data-slot="progress-track"
        className="block h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        <ProgressPrimitive.Indicator
          data-slot="progress-indicator"
          className="block h-full rounded-full bg-primary transition-[width]"
        />
      </ProgressPrimitive.Track>
    </ProgressPrimitive.Root>
  );
}

export { Progress };
