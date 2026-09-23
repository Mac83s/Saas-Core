"use client";

import { Toggle } from "@base-ui/react/toggle";
import { Toolbar as ToolbarPrimitive } from "@base-ui/react/toolbar";

import { cn } from "#lib/utils";

/** A row of controls with a single tab stop: arrow keys move between them
 *  (WAI-ARIA toolbar). Name it with `aria-label`. */
function Toolbar({ className, ...props }: ToolbarPrimitive.Root.Props) {
  return (
    <ToolbarPrimitive.Root
      data-slot="toolbar"
      className={cn(
        "flex flex-wrap items-center gap-0.5 rounded-md border bg-background p-1",
        className,
      )}
      {...props}
    />
  );
}

const item =
  "inline-flex h-8 min-w-8 shrink-0 items-center justify-center gap-1.5 rounded-sm px-2 text-sm font-medium outline-none select-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50 data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[pressed]:bg-primary/10 data-[pressed]:text-primary [&_svg]:size-4 [&_svg]:shrink-0";

function ToolbarButton({ className, ...props }: ToolbarPrimitive.Button.Props) {
  return (
    <ToolbarPrimitive.Button
      data-slot="toolbar-button"
      className={cn(item, className)}
      {...props}
    />
  );
}

/** A button that stays pressed while its state holds (bold, a list): it
 *  announces `aria-pressed`. */
function ToolbarToggle({
  className,
  pressed,
  onPressedChange,
  ...props
}: ToolbarPrimitive.Button.Props & {
  pressed: boolean;
  onPressedChange?: (pressed: boolean) => void;
}) {
  return (
    <ToolbarPrimitive.Button
      data-slot="toolbar-toggle"
      render={<Toggle pressed={pressed} onPressedChange={onPressedChange} />}
      className={cn(item, className)}
      {...props}
    />
  );
}

function ToolbarSeparator({
  className,
  ...props
}: ToolbarPrimitive.Separator.Props) {
  return (
    <ToolbarPrimitive.Separator
      data-slot="toolbar-separator"
      className={cn("mx-1 h-5 w-px bg-border", className)}
      {...props}
    />
  );
}

export { Toolbar, ToolbarButton, ToolbarSeparator, ToolbarToggle };
