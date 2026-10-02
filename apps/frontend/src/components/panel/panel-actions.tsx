"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { EllipsisIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@saas-core/ui/components/dropdown-menu";

export type PanelMoreAction = {
  label: string;
  icon?: ReactNode;
  onSelect: (trigger: HTMLElement) => void;
};

const PHONE = "(max-width: 639px)";

function subscribe(onChange: () => void) {
  const query = window.matchMedia?.(PHONE);
  query?.addEventListener("change", onChange);
  return () => query?.removeEventListener("change", onChange);
}

const isPhone = () => window.matchMedia?.(PHONE).matches ?? false;

/**
 * A page's actions in its header (R3, UX-004): the main one first, the rest
 * beside it on a wide screen and under „…”, with their names, on a phone —
 * so the main action never drops alone to a second row.
 */
export function PanelActions({
  children,
  more,
}: {
  /** The main action. */
  children?: ReactNode;
  more: readonly PanelMoreAction[];
}) {
  const t = useTranslations("DashboardNav");
  const phone = useSyncExternalStore(subscribe, isPhone, () => false);
  return (
    <>
      {children}
      {phone && more.length ? (
        <DropdownMenu>
          <DropdownMenuTrigger
            aria-label={t("more")}
            className={buttonVariants({ size: "icon", variant: "outline" })}
          >
            <EllipsisIcon aria-hidden="true" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {more.map((action) => (
              <DropdownMenuItem
                key={action.label}
                onClick={(event) => action.onSelect(event.currentTarget)}
              >
                {action.icon}
                {action.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : (
        more.map((action) => (
          <Button
            key={action.label}
            onClick={(event) => action.onSelect(event.currentTarget)}
            variant="outline"
          >
            {action.icon}
            {action.label}
          </Button>
        ))
      )}
    </>
  );
}
