"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import { ApiProblemError, confirmStepUp } from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { Link } from "#i18n/navigation";

/**
 * A change that needs a fresh code from the authenticator app (ADR-076, 31b;
 * owner answer 52a): `handled(error, again)` takes the server's
 * `step_up_required`, asks for the code and runs `again`;
 * `step_up_mfa_setup_required` says where to turn two-factor sign-in on. Any
 * other error is the caller's. `ui` goes where the notice should stand.
 */
export function useStepUp(): {
  handled: (error: unknown, again: () => Promise<unknown>) => boolean;
  ui: ReactNode;
} {
  const t = useTranslations("StepUp");
  const id = useId();
  const again = useRef<() => Promise<unknown>>(undefined);
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [problem, setProblem] = useState<string>();
  const [setup, setSetup] = useState(false);

  function handled(error: unknown, retry: () => Promise<unknown>): boolean {
    if (!(error instanceof ApiProblemError)) return false;
    if (error.problem.code === "step_up_required") {
      again.current = retry;
      setCode("");
      setProblem(undefined);
      setOpen(true);
      return true;
    }
    if (error.problem.code === "step_up_mfa_setup_required") {
      setSetup(true);
      return true;
    }
    return false;
  }

  async function confirm() {
    try {
      await confirmStepUp(code);
    } catch (error) {
      setProblem(
        error instanceof ApiProblemError &&
          error.problem.code === "step_up_locked"
          ? t("locked")
          : t("invalid"),
      );
      return;
    }
    setOpen(false);
    await again.current?.();
  }

  const ui = (
    <>
      {setup ? (
        <p className="text-sm text-destructive" role="alert">
          {t("setup")}{" "}
          <Link className="underline" href="/panel/settings/account">
            {t("setupLink")}
          </Link>
        </p>
      ) : null}
      <Dialog onOpenChange={setOpen} open={open}>
        <DialogContent closeLabel={t("cancel")}>
          <DialogHeader>
            <DialogTitle>{t("title")}</DialogTitle>
            <DialogDescription>{t("description")}</DialogDescription>
          </DialogHeader>
          <Field data-invalid={Boolean(problem)}>
            <FieldLabel htmlFor={id}>{t("code")}</FieldLabel>
            <Input
              aria-invalid={Boolean(problem)}
              autoComplete="one-time-code"
              className="max-w-xs"
              id={id}
              inputMode="numeric"
              onChange={(event) => setCode(event.target.value)}
              value={code}
            />
            {problem ? (
              <p className="text-sm text-destructive" role="alert">
                {problem}
              </p>
            ) : null}
          </Field>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {t("cancel")}
            </DialogClose>
            <Button
              disabled={code.trim().length < 6}
              onClick={() => void confirm()}
              type="button"
            >
              {t("confirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
  return { handled, ui };
}
