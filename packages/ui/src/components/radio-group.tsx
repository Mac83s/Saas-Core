"use client";

import { Radio as RadioPrimitive } from "@base-ui/react/radio";
import { RadioGroup as RadioGroupPrimitive } from "@base-ui/react/radio-group";

import { cn } from "#lib/utils";

/** One choice out of a few that are all worth reading (ADR-020: a list too
 *  short for a select). Name the group with `aria-labelledby`; wrap each
 *  `RadioGroupItem` in a `<label>` with its text for the name and a 44 px
 *  target. */
function RadioGroup({ className, ...props }: RadioGroupPrimitive.Props) {
  return (
    <RadioGroupPrimitive
      data-slot="radio-group"
      className={cn("grid w-full gap-2", className)}
      {...props}
    />
  );
}

function RadioGroupItem({ className, ...props }: RadioPrimitive.Root.Props) {
  return (
    <RadioPrimitive.Root
      data-slot="radio-group-item"
      className={cn(
        "peer inline-flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-full border border-input bg-background transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50 data-[checked]:border-primary data-[checked]:bg-primary data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50",
        className,
      )}
      {...props}
    >
      <RadioPrimitive.Indicator
        data-slot="radio-group-indicator"
        className="block size-2 rounded-full bg-primary-foreground"
      />
    </RadioPrimitive.Root>
  );
}

export { RadioGroup, RadioGroupItem };
