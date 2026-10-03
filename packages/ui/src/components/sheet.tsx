"use client";

import * as React from "react";
import { Drawer as DrawerPrimitive } from "@base-ui/react/drawer";
import { XIcon } from "lucide-react";

import { cn } from "#lib/utils";
import { Button } from "#components/button";

/**
 * A sheet (UX-085): filters, a preview or a panel over the page — from the
 * bottom on a phone, from the right on a computer. It is a modal dialog: focus
 * stays inside and returns to whatever opened it, Esc, a press on the backdrop
 * and a swipe towards the edge close it. The body scrolls; the footer with the
 * sheet's actions stays in view.
 */

type SheetSide = "auto" | "bottom" | "right";

const WIDE_QUERY = "(min-width: 768px)";

function wideSnapshot() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(WIDE_QUERY).matches
  );
}

function subscribeWide(onChange: () => void) {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return () => undefined;
  }
  const query = window.matchMedia(WIDE_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

const SheetSideContext = React.createContext<"bottom" | "right">("bottom");

function Sheet({
  side = "auto",
  ...props
}: Omit<DrawerPrimitive.Root.Props, "swipeDirection"> & { side?: SheetSide }) {
  const wide = React.useSyncExternalStore(
    subscribeWide,
    wideSnapshot,
    () => false,
  );
  const resolved = side === "auto" ? (wide ? "right" : "bottom") : side;
  return (
    <SheetSideContext.Provider value={resolved}>
      <DrawerPrimitive.Root
        swipeDirection={resolved === "right" ? "right" : "down"}
        {...props}
      />
    </SheetSideContext.Provider>
  );
}

const SheetTrigger = DrawerPrimitive.Trigger;
const SheetClose = DrawerPrimitive.Close;

function SheetContent({
  className,
  children,
  closeLabel = "Close",
  showCloseButton = true,
  ...props
}: DrawerPrimitive.Popup.Props & {
  closeLabel?: string;
  showCloseButton?: boolean;
}) {
  const side = React.useContext(SheetSideContext);
  return (
    <DrawerPrimitive.Portal>
      <DrawerPrimitive.Backdrop className="fixed inset-0 z-50 bg-black/50 opacity-[calc(1-var(--drawer-swipe-progress,0))] transition-opacity duration-300 data-ending-style:opacity-0 data-starting-style:opacity-0 data-swiping:duration-0 motion-reduce:transition-none dark:bg-black/70" />
      <DrawerPrimitive.Viewport
        className={cn(
          "fixed inset-0 z-50 flex",
          side === "right" ? "justify-end" : "items-end",
        )}
      >
        {/* Base UI makes the page behind inert; aria-modal says so to the
            screen readers that do not read inertness. */}
        <DrawerPrimitive.Popup
          aria-modal="true"
          data-side={side}
          data-slot="sheet-content"
          className={cn(
            "relative flex flex-col bg-background text-foreground shadow-xl outline-none transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] data-swiping:select-none data-swiping:duration-0 motion-reduce:transition-none dark:bg-card",
            side === "right"
              ? "h-full w-[min(28rem,100vw)] border-l [transform:translateX(var(--drawer-swipe-movement-x,0))] data-ending-style:[transform:translateX(100%)] data-starting-style:[transform:translateX(100%)]"
              : "max-h-[85dvh] w-full rounded-t-2xl border-t [transform:translateY(var(--drawer-swipe-movement-y,0))] data-ending-style:[transform:translateY(100%)] data-starting-style:[transform:translateY(100%)]",
            className,
          )}
          {...props}
        >
          {side === "bottom" ? (
            <div
              aria-hidden="true"
              className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-muted-foreground/30"
            />
          ) : null}
          <DrawerPrimitive.Content className="flex min-h-0 flex-1 flex-col">
            {children}
          </DrawerPrimitive.Content>
          {showCloseButton && (
            <DrawerPrimitive.Close
              aria-label={closeLabel}
              render={
                <Button
                  className="absolute top-3 right-3"
                  size="icon-sm"
                  variant="ghost"
                />
              }
            >
              <XIcon aria-hidden="true" />
            </DrawerPrimitive.Close>
          )}
        </DrawerPrimitive.Popup>
      </DrawerPrimitive.Viewport>
    </DrawerPrimitive.Portal>
  );
}

function SheetHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-header"
      className={cn("space-y-1.5 px-4 pt-4 pr-12 pb-2 md:px-6", className)}
      {...props}
    />
  );
}

/** The part that scrolls when the sheet is taller than the screen. */
function SheetBody({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-body"
      className={cn(
        "min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-2 md:px-6",
        className,
      )}
      {...props}
    />
  );
}

/** The sheet's actions: always in view, above a phone's home indicator. */
function SheetFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-footer"
      className={cn(
        "flex shrink-0 flex-col-reverse gap-2 border-t px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:flex-row sm:justify-end md:px-6",
        className,
      )}
      {...props}
    />
  );
}

function SheetTitle({ className, ...props }: DrawerPrimitive.Title.Props) {
  return (
    <DrawerPrimitive.Title
      data-slot="sheet-title"
      className={cn("text-lg font-semibold", className)}
      {...props}
    />
  );
}

function SheetDescription({
  className,
  ...props
}: DrawerPrimitive.Description.Props) {
  return (
    <DrawerPrimitive.Description
      data-slot="sheet-description"
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

export {
  Sheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
  type SheetSide,
};
