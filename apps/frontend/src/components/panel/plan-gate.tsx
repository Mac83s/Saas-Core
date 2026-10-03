import type { ReactNode } from "react";
import { LockKeyholeIcon } from "lucide-react";

import { buttonVariants } from "@saas-core/ui/components/button";

import { Link } from "#i18n/navigation";

/**
 * A feature the plan leaves out, said calmly rather than as a failure
 * (UX-045, the pattern of Wiadomości): what it gives and, for whoever may
 * change the plan, the way to the plans. Nobody else gets a button they
 * cannot use — the text tells them whom to ask.
 */
export function PlanGate({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: { href: string; label: string };
}) {
  return (
    <div className="flex flex-wrap items-start gap-3 rounded-lg border border-warning-foreground/25 bg-warning p-4 text-sm">
      <LockKeyholeIcon
        aria-hidden="true"
        className="mt-0.5 size-5 shrink-0 text-warning-foreground"
      />
      <div className="min-w-0 flex-1 basis-56 space-y-1">
        <p className="font-medium">{title}</p>
        <p className="text-muted-foreground">{children}</p>
      </div>
      {action ? (
        <Link className={buttonVariants()} href={action.href}>
          {action.label}
        </Link>
      ) : null}
    </div>
  );
}
