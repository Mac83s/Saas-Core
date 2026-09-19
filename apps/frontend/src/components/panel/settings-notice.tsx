import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

/**
 * In place of a settings form the person cannot use here: no right to it, or
 * no company chosen yet. Says why and what to do instead of answering 403.
 */
export function SettingsNotice({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon;
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="flex max-w-3xl items-start gap-3 rounded-xl border bg-muted/40 p-5">
      <Icon
        aria-hidden="true"
        className="mt-0.5 size-5 shrink-0 text-muted-foreground"
      />
      <div className="space-y-1">
        <h2 className="font-medium">{title}</h2>
        <p className="text-sm text-muted-foreground">{children}</p>
      </div>
    </section>
  );
}
