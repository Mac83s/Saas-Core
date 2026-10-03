"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  ApiProblemError,
  getCommandConsent,
  grantCommandConsent,
  type AssistantConsentGroup,
  type CommandConsent,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";

import { useStepUp } from "../../core/organizations/step-up";

type Locale = "pl" | "en";
type Answer = { consents: Record<string, string>; declined: boolean };

function stale(error: unknown): boolean {
  return (
    error instanceof ApiProblemError &&
    error.problem.code === "consent_preview_not_found"
  );
}

/**
 * What the assistant asks to do, as the server previewed it — never the
 * model's own account of it (ADR-076 §3). One click agrees to one group; a
 * plan with a publication or something that cannot be undone has several, and
 * each is its own question. Closing the dialog leaves the plan waiting.
 */
export function ConsentDialog({
  groups,
  open,
  onOpenChange,
  onAnswer,
  onStale,
}: {
  groups: AssistantConsentGroup[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The tokens of the groups agreed to, or the whole plan declined. */
  onAnswer: (answer: Answer) => Promise<void>;
  /** The preview is gone from the server: the conversation offers it again. */
  onStale: () => Promise<void>;
}) {
  const t = useTranslations("Assistant");
  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent closeLabel={t("consentLater")}>
        {open ? (
          // A plan offered again has new digests: its questions start over.
          <Questions
            close={() => onOpenChange(false)}
            groups={groups}
            key={groups.map((group) => group.digest).join(":")}
            onAnswer={onAnswer}
            onStale={onStale}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function Questions({
  groups,
  close,
  onAnswer,
  onStale,
}: {
  groups: AssistantConsentGroup[];
  close: () => void;
  onAnswer: (answer: Answer) => Promise<void>;
  onStale: () => Promise<void>;
}) {
  const [index, setIndex] = useState(0);
  const tokens = useRef<Record<string, string>>({});
  const group = groups[index];
  if (!group) return null;
  const more = index + 1 < groups.length;

  async function finish(declined: boolean) {
    await onAnswer({ consents: tokens.current, declined });
    close();
  }

  return (
    <Question
      group={group}
      key={group.digest}
      onAgreed={async (token) => {
        tokens.current[group.id] = token;
        if (more) setIndex(index + 1);
        else await finish(false);
      }}
      // "Anuluj": this group does not run — nor anything, if none was agreed.
      onDeclined={async () => {
        const agreed = Object.keys(tokens.current).length > 0;
        if (agreed && more) setIndex(index + 1);
        else await finish(!agreed);
      }}
      onStale={onStale}
      step={
        groups.length > 1 ? { step: index + 1, total: groups.length } : null
      }
    />
  );
}

function Question({
  group,
  step,
  onAgreed,
  onDeclined,
  onStale,
}: {
  group: AssistantConsentGroup;
  step: { step: number; total: number } | null;
  onAgreed: (token: string) => Promise<void>;
  onDeclined: () => Promise<void>;
  onStale: () => Promise<void>;
}) {
  const t = useTranslations("Assistant");
  const locale = useLocale() as Locale;
  const stepUp = useStepUp(t("consentStepUp"));
  const [plan, setPlan] = useState<CommandConsent>();
  const [problem, setProblem] = useState<string>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getCommandConsent(group.digest)
      .then((shown) => {
        if (!cancelled) setPlan(shown);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (stale(error)) void onStale();
        else setProblem(t("consentLoadError"));
      });
    return () => {
      cancelled = true;
    };
  }, [group.digest, onStale, t]);

  async function settle(decision: () => Promise<void>) {
    setBusy(true);
    setProblem(undefined);
    try {
      await decision();
    } catch (error) {
      if (stale(error)) await onStale();
      else setProblem(t("consentAnswerError"));
    } finally {
      setBusy(false);
    }
  }

  async function agree(): Promise<void> {
    await settle(async () => {
      let token: string;
      try {
        token = await grantCommandConsent(group.digest);
      } catch (error) {
        // A step-up asks for the code and then comes back here.
        if (stepUp.handled(error, agree)) return;
        throw error;
      }
      await onAgreed(token);
    });
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t("consentTitle")}</DialogTitle>
        <DialogDescription>
          {step ? t("consentStepOf", step) : t("consentDescription")}
        </DialogDescription>
      </DialogHeader>
      <div className="max-h-[50dvh] space-y-4 overflow-y-auto">
        {plan ? (
          <>
            {plan.risk === "publish" || plan.risk === "irreversible" ? (
              <Badge variant="warning">{t(`risk_${plan.risk}`)}</Badge>
            ) : null}
            <ul className="space-y-3">
              {plan.calls.map((call) => (
                <li className="space-y-1" key={call.step_id}>
                  <p className="font-medium">{call.title[locale]}</p>
                  {call.effects.length ? (
                    <ul className="list-disc space-y-0.5 pl-5 text-sm text-muted-foreground">
                      {call.effects.map((effect, position) => (
                        <li key={position}>{effect.summary[locale]}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      {call.summary[locale]}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </>
        ) : problem ? null : (
          <p className="text-sm text-muted-foreground" role="status">
            {t("consentLoading")}
          </p>
        )}
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        {stepUp.ui}
      </div>
      <DialogFooter>
        <Button
          disabled={busy}
          onClick={() => void settle(onDeclined)}
          type="button"
          variant="outline"
        >
          {t("consentCancel")}
        </Button>
        <Button
          disabled={busy || !plan}
          onClick={() => void agree()}
          type="button"
        >
          {t("consentAgree")}
        </Button>
      </DialogFooter>
    </>
  );
}
