"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import { MenuIcon, PanelLeftCloseIcon, PanelLeftOpenIcon } from "lucide-react";

import { cn } from "#lib/utils";
import { Button } from "#components/button";

type SidebarContextValue = {
  collapsed: boolean;
  mobileOpen: boolean;
  isMobile: boolean;
  setMobileOpen: (open: boolean) => void;
  closeMobile: () => void;
  toggle: () => void;
};

const SidebarContext = createContext<SidebarContextValue | null>(null);

export function useSidebar() {
  const value = useContext(SidebarContext);
  if (!value) throw new Error("Sidebar components require SidebarProvider.");
  return value;
}

export function SidebarProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const isMobile = useSyncExternalStore(
    subscribeMobileViewport,
    mobileViewportSnapshot,
    () => false,
  );
  useEffect(() => {
    if (!isMobile) setMobileOpen(false);
  }, [isMobile]);
  const closeMobile = useCallback(() => setMobileOpen(false), []);
  const value = useMemo(
    () => ({
      collapsed,
      isMobile,
      mobileOpen,
      setMobileOpen,
      closeMobile,
      toggle: () => {
        if (isMobile) {
          setMobileOpen((current) => !current);
        } else {
          setCollapsed((current) => !current);
        }
      },
    }),
    [closeMobile, collapsed, isMobile, mobileOpen],
  );
  return (
    <SidebarContext.Provider value={value}>
      <div
        className="group/sidebar-wrapper flex min-h-svh w-full bg-background"
        data-collapsed={collapsed || undefined}
      >
        {children}
      </div>
    </SidebarContext.Provider>
  );
}

export function Sidebar({
  className,
  mobileCloseLabel = "Close navigation",
  ...props
}: HTMLAttributes<HTMLElement> & { mobileCloseLabel?: string }) {
  const { collapsed, isMobile, mobileOpen, closeMobile } = useSidebar();
  const sidebarRef = useRef<HTMLElement>(null);
  const mobileDialogOpen = isMobile && mobileOpen;

  useEffect(() => {
    if (!mobileDialogOpen) return;
    const sidebar = sidebarRef.current;
    if (!sidebar) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusable = () =>
      Array.from(
        sidebar.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hasAttribute("hidden"));
    focusable()[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        // A menu open inside the drawer handles its own Escape first.
        if (event.defaultPrevented) return;
        event.preventDefault();
        closeMobile();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusable();
      const first = elements[0];
      const last = elements.at(-1);
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [closeMobile, mobileDialogOpen]);

  return (
    <>
      {mobileDialogOpen ? (
        <button
          aria-label={mobileCloseLabel}
          className="fixed inset-0 z-40 bg-foreground/20 backdrop-blur-[1px] lg:hidden"
          onClick={closeMobile}
          type="button"
        />
      ) : null}
      <aside
        aria-modal={mobileDialogOpen ? "true" : undefined}
        className={cn(
          "invisible fixed inset-y-0 left-0 z-50 flex w-64 -translate-x-full flex-col border-r bg-muted shadow-xl transition-[width,transform] duration-200 lg:visible lg:sticky lg:top-0 lg:z-20 lg:h-svh lg:translate-x-0 lg:shadow-none",
          collapsed && "lg:w-20",
          mobileOpen && "visible translate-x-0",
          className,
        )}
        data-collapsed={collapsed || undefined}
        ref={sidebarRef}
        role={mobileDialogOpen ? "dialog" : undefined}
        {...props}
      />
    </>
  );
}

export function SidebarHeader({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-2.5 pt-4 pb-2", className)} {...props} />;
}

export function SidebarContent({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex-1 overflow-y-auto px-2.5 py-2", className)}
      {...props}
    />
  );
}

export function SidebarFooter({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-2.5 pt-2 pb-4", className)} {...props} />;
}

export function SidebarInset({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  const { isMobile, mobileOpen } = useSidebar();
  const backgroundInert = isMobile && mobileOpen;
  return (
    <div
      aria-hidden={backgroundInert ? "true" : undefined}
      className={cn("min-w-0 flex-1", className)}
      inert={backgroundInert ? true : undefined}
      {...props}
    />
  );
}

export function SidebarTrigger({
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  const { collapsed, isMobile, mobileOpen, toggle } = useSidebar();
  return (
    <Button
      aria-label={collapsed ? "Expand navigation" : "Toggle navigation"}
      aria-expanded={isMobile ? mobileOpen : !collapsed}
      className={className}
      onClick={toggle}
      size="icon-sm"
      type="button"
      variant="ghost"
      {...props}
    >
      <MenuIcon aria-hidden="true" className="lg:hidden" />
      {collapsed ? (
        <PanelLeftOpenIcon aria-hidden="true" className="hidden lg:block" />
      ) : (
        <PanelLeftCloseIcon aria-hidden="true" className="hidden lg:block" />
      )}
    </Button>
  );
}

const MOBILE_MEDIA_QUERY = "(max-width: 1023px)";

function mobileViewportSnapshot() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia(MOBILE_MEDIA_QUERY).matches
  );
}

function subscribeMobileViewport(onChange: () => void) {
  if (
    typeof window === "undefined" ||
    typeof window.matchMedia !== "function"
  ) {
    return () => undefined;
  }
  const query = window.matchMedia(MOBILE_MEDIA_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
