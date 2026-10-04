"use client";

import { Checkbox as CheckboxPrimitive } from "@base-ui/react/checkbox";
import { CheckIcon } from "lucide-react";

import { cn } from "#lib/utils";

/** Something a person ticks to say yes to — a statement they confirm, a row
 *  they choose. A setting that is on or off is a `Switch`. Wrap it in a
 *  `<label>` with its text for the name and a 44 px target. */
function Checkbox({ className, ...props }: CheckboxPrimitive.Root.Props) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        "peer inline-flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-sm border border-input bg-background transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50 data-[checked]:border-primary data-[checked]:bg-primary data-[checked]:text-primary-foreground data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50",
        className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator
        data-slot="checkbox-indicator"
        className="flex items-center justify-center"
      >
        <CheckIcon aria-hidden="true" className="size-3.5" />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export { Checkbox };
