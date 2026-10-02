"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { usePathname } from "#i18n/navigation";

/**
 * The header's menu below the inline breakpoint. A native disclosure, so it
 * opens before any script has loaded; once one of its links is followed it
 * folds, instead of staying open over the page it led to.
 */
export function MobileMenu({
  label,
  className,
  children,
}: {
  label: string;
  className: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  const pathname = usePathname();
  const shown = useRef(pathname);

  useEffect(() => {
    // Not on mount: a menu opened before hydration stays open.
    if (shown.current === pathname) return;
    shown.current = pathname;
    ref.current?.removeAttribute("open");
  }, [pathname]);

  return (
    <details
      ref={ref}
      className={className}
      onClick={(event) => {
        // Any followed link, including one to the same page (/#features).
        if ((event.target as Element).closest("a[href]")) {
          ref.current?.removeAttribute("open");
        }
      }}
    >
      <summary className="cursor-pointer px-5 py-3 text-sm font-medium">
        {label}
      </summary>
      {children}
    </details>
  );
}
