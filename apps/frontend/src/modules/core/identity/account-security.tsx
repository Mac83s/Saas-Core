"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { MailIcon, ShieldCheckIcon } from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  beginTotpSetup,
  confirmTotpSetup,
  requestPasswordReset,
  type TotpSetup,
} from "@saas-core/api-client";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

/**
 * The API changes a password only through an e-mailed link (the reset flow,
 * which then signs out every device), so that is what the account offers.
 */
export function PasswordCard({ email }: { email: string }) {
  const t = useTranslations("Settings");
  const [state, setState] = useState<"idle" | "sending" | "sent" | "failed">(
    "idle",
  );

  async function send() {
    setState("sending");
    try {
      await requestPasswordReset({ email });
      setState("sent");
    } catch {
      setState("failed");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("passwordTitle")}</CardTitle>
        <CardDescription>{t("passwordDescription", { email })}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button
          disabled={state === "sending" || state === "sent"}
          onClick={() => void send()}
          variant="outline"
        >
          <MailIcon aria-hidden="true" />
          {state === "sending" ? t("passwordSending") : t("passwordSend")}
        </Button>
        <p aria-live="polite" className="text-sm text-muted-foreground">
          {state === "sent" ? t("passwordSent", { email }) : null}
        </p>
        {state === "failed" ? (
          <p className="text-sm text-destructive" role="alert">
            {t("passwordFailed")}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

type Step = "start" | "scan" | "codes" | "on";

/**
 * Two-step sign-in with an authenticator app (TOTP). The API can switch it on,
 * but neither reports whether it is on nor switches it off: the card offers
 * the setup and learns that it is already on from the answer.
 */
export function TwoFactorCard() {
  const t = useTranslations("Settings");
  const identity = useTranslations("Identity");
  const common = useTranslations("Common");
  const [step, setStep] = useState<Step>("start");
  const [setup, setSetup] = useState<TotpSetup>();
  const [codes, setCodes] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState<string>();
  const schema = useMemo(
    () =>
      z.object({
        code: z
          .string()
          .trim()
          .regex(/^\d{6}$/, t("mfaCode")),
      }),
    [t],
  );
  const form = useForm<{ code: string }>({
    resolver: zodResolver(schema),
    defaultValues: { code: "" },
  });
  const codeError = form.formState.errors.code;
  const startButton = useRef<HTMLButtonElement>(null);
  const outcome = useRef<HTMLParagraphElement>(null);

  // Each step replaces the control that led to it; focus follows, so keyboard
  // and screen reader users are not dropped back to the top of the page.
  useEffect(() => {
    if (step === "scan") form.setFocus("code");
    else if (step !== "start") outcome.current?.focus();
    else if (setup) startButton.current?.focus();
  }, [form, setup, step]);

  async function start() {
    setStarting(true);
    setProblem(undefined);
    try {
      setSetup(await beginTotpSetup());
      setStep("scan");
    } catch (error) {
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "mfa_already_enabled"
      )
        setStep("on");
      else setProblem(t("mfaError"));
    } finally {
      setStarting(false);
    }
  }

  async function confirm({ code }: { code: string }) {
    setProblem(undefined);
    try {
      setCodes((await confirmTotpSetup(code)).recovery_codes);
      setStep("codes");
    } catch (error) {
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "invalid_mfa_code"
      )
        form.setError("code", {
          type: "server",
          message: identity("invalidMfaCode"),
        });
      else setProblem(t("mfaError"));
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("mfaTitle")}</CardTitle>
        <CardDescription>{t("mfaDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {step === "start" ? (
          <Button
            disabled={starting}
            onClick={() => void start()}
            ref={startButton}
            variant="outline"
          >
            {starting ? t("mfaStarting") : t("mfaStart")}
          </Button>
        ) : null}
        {step === "on" ? (
          <p
            className="flex items-center gap-2 text-sm font-medium outline-none"
            ref={outcome}
            tabIndex={-1}
          >
            <ShieldCheckIcon
              aria-hidden="true"
              className="size-4 text-primary"
            />
            {t("mfaOn")}
          </p>
        ) : null}
        {step === "scan" && setup ? (
          <form
            className="space-y-4"
            noValidate
            onSubmit={form.handleSubmit(confirm)}
          >
            <ol className="list-decimal space-y-3 pl-5 text-sm">
              <li className="space-y-2">
                <p>{t("mfaScan")}</p>
                <div className="rounded-lg border bg-muted/40 p-3">
                  <p className="text-xs text-muted-foreground">
                    {identity("manualSecret")}
                  </p>
                  <code className="font-mono text-sm break-all">
                    {setup.secret.match(/.{1,4}/g)?.join(" ")}
                  </code>
                </div>
                <a
                  className={buttonVariants({ variant: "outline" })}
                  href={setup.provisioning_uri}
                >
                  {t("mfaOpenApp")}
                </a>
              </li>
              <li>{t("mfaEnterCode")}</li>
            </ol>
            <Field data-invalid={Boolean(codeError)}>
              <FieldLabel htmlFor="mfa-code">
                {identity("confirmationCode")}
              </FieldLabel>
              <Input
                aria-invalid={Boolean(codeError)}
                autoComplete="one-time-code"
                className="max-w-48 font-mono tracking-widest"
                id="mfa-code"
                inputMode="numeric"
                maxLength={6}
                {...form.register("code")}
              />
              <FieldError errors={[codeError]} />
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button disabled={form.formState.isSubmitting} type="submit">
                {form.formState.isSubmitting
                  ? identity("checking")
                  : t("mfaConfirm")}
              </Button>
              <Button
                onClick={() => {
                  form.reset();
                  setProblem(undefined);
                  setStep("start");
                }}
                type="button"
                variant="outline"
              >
                {common("cancel")}
              </Button>
            </div>
          </form>
        ) : null}
        {step === "codes" ? (
          <div className="space-y-3">
            <p
              className="text-sm font-medium outline-none"
              ref={outcome}
              tabIndex={-1}
            >
              {t("mfaEnabled")}
            </p>
            <p className="text-sm">{identity("copyRecoveryCodes")}</p>
            <ul
              aria-label={t("mfaRecoveryCodes")}
              className="grid grid-cols-2 gap-2 rounded-lg border bg-muted/40 p-3 font-mono text-sm"
            >
              {codes.map((code) => (
                <li key={code}>{code}</li>
              ))}
            </ul>
            <Button onClick={() => setStep("on")}>{t("mfaCodesSaved")}</Button>
          </div>
        ) : null}
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
