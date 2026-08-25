"use client";

import { Tabs as TabsPrimitive } from "@base-ui/react/tabs";

import { cn } from "#lib/utils";

function Tabs({ className, ...props }: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      className={cn("flex flex-col gap-6", className)}
      {...props}
    />
  );
}

function TabsList({
  className,
  // Arrow keys select as they move, matching how a mouse user experiences the
  // strip. The panels here are cheap to render, so the usual argument for
  // manual activation — an expensive panel behind every arrow press — does not
  // apply. Pass `activateOnFocus={false}` where it does.
  activateOnFocus = true,
  ...props
}: TabsPrimitive.List.Props) {
  return (
    <TabsPrimitive.List
      activateOnFocus={activateOnFocus}
      data-slot="tabs-list"
      className={cn(
        // Scrolls rather than wraps: on a narrow screen a wrapped tab strip
        // pushes the panel below the fold before anything has been read.
        "relative flex w-full shrink-0 gap-1 overflow-x-auto border-b border-border",
        className,
      )}
      {...props}
    />
  );
}

function TabsTab({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-tab"
      className={cn(
        "inline-flex shrink-0 items-center gap-2 whitespace-nowrap rounded-t-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors outline-none select-none",
        "hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50",
        "data-[selected]:text-foreground",
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className,
      )}
      {...props}
    />
  );
}

function TabsIndicator({ className, ...props }: TabsPrimitive.Indicator.Props) {
  return (
    <TabsPrimitive.Indicator
      data-slot="tabs-indicator"
      className={cn(
        "absolute bottom-0 left-0 z-10 h-0.5 bg-primary transition-all duration-200",
        "w-[var(--active-tab-width)] translate-x-[var(--active-tab-left)]",
        className,
      )}
      {...props}
    />
  );
}

function TabsPanel({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-panel"
      className={cn("outline-none", className)}
      {...props}
    />
  );
}

export { Tabs, TabsIndicator, TabsList, TabsPanel, TabsTab };
