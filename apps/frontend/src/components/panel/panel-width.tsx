"use client";

import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Maximize2Icon, Minimize2Icon } from "lucide-react";
import { useTranslations } from "next-intl";

import { PANEL_WIDTH_COOKIE } from "#lib/panel-width";
import { cn } from "@saas-core/ui/lib/utils";

const WidthContext = createContext<{
  wide: boolean;
  setWide: (wide: boolean) => void;
}>({ wide: false, setWide: () => undefined });

export function PanelWidthProvider({
  initialWide,
  children,
}: {
  initialWide: boolean;
  children: ReactNode;
}) {
  const [wide, setState] = useState(initialWide);
  const value = useMemo(
    () => ({
      wide,
      setWide: (next: boolean) => {
        setState(next);
        // A year: the choice belongs to this browser, like the colour scheme.
        document.cookie = `${PANEL_WIDTH_COOKIE}=${next ? "full" : "default"}; path=/; max-age=31536000; samesite=lax`;
      },
    }),
    [wide],
  );
  return (
    <WidthContext.Provider value={value}>{children}</WidthContext.Provider>
  );
}

/**
 * Every panel page sits in this one box (ADR-057): a comfortable reading
 * width by default, edge to edge on request. Pages never set their own width.
 */
export function PanelMain({ children }: { children: ReactNode }) {
  const { wide } = useContext(WidthContext);
  return (
    <main
      className={cn(
        "mx-auto w-full flex-1 px-4 pt-6 pb-24 sm:px-6 lg:px-8 lg:pt-8 lg:pb-12",
        !wide && "max-w-7xl",
      )}
      id="panel-main"
    >
      {children}
    </main>
  );
}

/** Only where it changes something: below 1536 px the box is already full. */
export function WidthToggle() {
  const t = useTranslations("DashboardNav");
  const { wide, setWide } = useContext(WidthContext);
  // A toggle keeps one name; aria-pressed says which way it stands.
  const label = t("wideView");
  const Icon = wide ? Minimize2Icon : Maximize2Icon;
  return (
    <button
      aria-label={label}
      aria-pressed={wide}
      className="flex size-11 items-center justify-center rounded-lg border border-foreground/15 transition-colors hover:bg-foreground/6 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring max-2xl:hidden"
      onClick={() => setWide(!wide)}
      title={label}
      type="button"
    >
      <Icon aria-hidden="true" className="size-4" />
    </button>
  );
}
