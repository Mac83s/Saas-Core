"use client";

import { useMemo, useState } from "react";
import type { ComponentProps, ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Controller,
  useForm,
  type UseFormRegisterReturn,
} from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  beginTotpSetup,
  completeMfaLogin,
  confirmEmailVerification,
  confirmPasswordReset,
  confirmTotpSetup,
  loginAccount,
  registerAccount,
  requestEmailVerification,
  requestPasswordReset,
  type TotpSetup,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@saas-core/ui/components/select";

import { Link, useRouter } from "#i18n/navigation";
import { identityErrorMessage, identityFieldError } from "./problem";

type LoginValues = { email: string; password: string };
type RegistrationValues = LoginValues & { locale: "pl" | "en" };
type CodeValues = { code: string };
type EmailValues = { email: string };
type ResetValues = { password: string; passwordRepeat: string };
type IdentityTranslator = ReturnType<typeof useTranslations<"Identity">>;

function emailSchema(t: IdentityTranslator) {
  return z.string().email(t("validationEmail"));
}

function passwordSchema(t: IdentityTranslator) {
  return z.string().min(12, t("validationPassword"));
}

function problemMessages(t: IdentityTranslator) {
  return {
    invalidCredentials: t("invalidCredentials"),
    invalidMfaCode: t("invalidMfaCode"),
    mfaSetupRequired: t("mfaSetupRequired"),
    apiUnavailable: t("apiUnavailable"),
  };
}

export function LoginForm({ returnTo = "/panel" }: { returnTo?: string }) {
  const t = useTranslations("Identity");
  const router = useRouter();
  const [stage, setStage] = useState<"password" | "mfa" | "setup">("password");
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [problem, setProblem] = useState<string>();
  const loginSchema = useMemo(
    () =>
      z.object({
        email: emailSchema(t),
        password: z.string().min(1, t("validationPasswordRequired")),
      }),
    [t],
  );
  const codeSchema = useMemo(
    () => z.object({ code: z.string().min(6, t("validationCode")) }),
    [t],
  );
  const form = useForm<LoginValues>({ resolver: zodResolver(loginSchema) });
  const codeForm = useForm<CodeValues>({ resolver: zodResolver(codeSchema) });

  async function submitPassword(values: LoginValues) {
    setProblem(undefined);
    try {
      const result = await loginAccount(values);
      if (result.kind === "mfa_required") {
        setStage("mfa");
        return;
      }
      router.replace(returnTo);
      router.refresh();
    } catch (error) {
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "mfa_setup_required"
      ) {
        try {
          setSetup(await beginTotpSetup());
          setStage("setup");
          return;
        } catch (setupError) {
          setProblem(identityErrorMessage(setupError, problemMessages(t)));
          return;
        }
      }
      const emailError = identityFieldError(error, "email");
      const passwordError = identityFieldError(error, "password");
      if (emailError)
        form.setError("email", { type: "server", message: emailError });
      if (passwordError)
        form.setError("password", { type: "server", message: passwordError });
      setProblem(identityErrorMessage(error, problemMessages(t)));
    }
  }

  async function submitCode(values: CodeValues) {
    setProblem(undefined);
    try {
      if (stage === "setup") {
        const result = await confirmTotpSetup(values.code);
        setRecoveryCodes(result.recovery_codes);
        return;
      }
      await completeMfaLogin(values.code);
      router.replace(returnTo);
      router.refresh();
    } catch (error) {
      const codeError = identityFieldError(error, "code");
      if (codeError)
        codeForm.setError("code", { type: "server", message: codeError });
      setProblem(identityErrorMessage(error, problemMessages(t)));
    }
  }

  if (recoveryCodes.length > 0) {
    return (
      <div className="space-y-4">
        <Notice>{t("copyRecoveryCodes")}</Notice>
        <ul className="grid grid-cols-2 gap-2 rounded-lg border bg-muted/40 p-3 font-mono text-xs">
          {recoveryCodes.map((code) => (
            <li key={code}>{code}</li>
          ))}
        </ul>
        <Button className="w-full" onClick={() => router.replace(returnTo)}>
          {t("codesSaved")}
        </Button>
      </div>
    );
  }

  if (stage !== "password") {
    return (
      <form className="space-y-5" onSubmit={codeForm.handleSubmit(submitCode)}>
        {stage === "setup" && setup && (
          <div className="space-y-3">
            <Notice>{t("setupMfa")}</Notice>
            <div className="rounded-lg border bg-muted/40 p-3 text-xs break-all">
              <p className="font-medium">{t("manualSecret")}</p>
              <code>{setup.secret}</code>
              <p className="mt-2 text-muted-foreground">
                {setup.provisioning_uri}
              </p>
            </div>
          </div>
        )}
        <TextField
          autoComplete="one-time-code"
          error={codeForm.formState.errors.code?.message}
          label={
            stage === "setup" ? t("confirmationCode") : t("mfaOrRecoveryCode")
          }
          registration={codeForm.register("code")}
        />
        {problem && <Problem message={problem} />}
        <Button
          className="w-full"
          disabled={codeForm.formState.isSubmitting}
          type="submit"
        >
          {codeForm.formState.isSubmitting
            ? t("checking")
            : t("confirmAndSignIn")}
        </Button>
      </form>
    );
  }

  return (
    <form className="space-y-5" onSubmit={form.handleSubmit(submitPassword)}>
      <FieldGroup>
        <TextField
          autoComplete="email"
          error={form.formState.errors.email?.message}
          label={t("email")}
          registration={form.register("email")}
          type="email"
        />
        <TextField
          autoComplete="current-password"
          error={form.formState.errors.password?.message}
          label={t("password")}
          registration={form.register("password")}
          type="password"
        />
      </FieldGroup>
      {problem && <Problem message={problem} />}
      <Button
        className="w-full"
        disabled={form.formState.isSubmitting}
        type="submit"
      >
        {form.formState.isSubmitting ? t("signingIn") : t("signIn")}
      </Button>
      <div className="flex justify-between text-sm">
        <Link className="text-primary hover:underline" href="/password-reset">
          {t("forgotPassword")}
        </Link>
        <Link className="text-primary hover:underline" href="/register">
          {t("createAccount")}
        </Link>
      </div>
    </form>
  );
}

export function RegistrationForm() {
  const t = useTranslations("Identity");
  const locale = useLocale();
  const [message, setMessage] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const registrationSchema = useMemo(
    () =>
      z.object({
        email: emailSchema(t),
        password: passwordSchema(t),
        locale: z.enum(["pl", "en"]),
      }),
    [t],
  );
  const form = useForm<RegistrationValues>({
    resolver: zodResolver(registrationSchema),
    defaultValues: { locale: locale === "en" ? "en" : "pl" },
  });
  async function submit(values: RegistrationValues) {
    setProblem(undefined);
    try {
      setMessage(await registerAccount(values));
    } catch (error) {
      const emailError = identityFieldError(error, "email");
      const passwordError = identityFieldError(error, "password");
      if (emailError)
        form.setError("email", { type: "server", message: emailError });
      if (passwordError)
        form.setError("password", { type: "server", message: passwordError });
      setProblem(identityErrorMessage(error, problemMessages(t)));
    }
  }
  if (message) return <Notice>{message}</Notice>;
  return (
    <form className="space-y-5" onSubmit={form.handleSubmit(submit)}>
      <FieldGroup>
        <TextField
          autoComplete="email"
          error={form.formState.errors.email?.message}
          label={t("email")}
          registration={form.register("email")}
          type="email"
        />
        <TextField
          autoComplete="new-password"
          description={t("passwordHint")}
          error={form.formState.errors.password?.message}
          label={t("password")}
          registration={form.register("password")}
          type="password"
        />
        <Controller
          control={form.control}
          name="locale"
          render={({ field }) => (
            <Field>
              <FieldLabel htmlFor="locale">
                {t("communicationLanguage")}
              </FieldLabel>
              <Select onValueChange={field.onChange} value={field.value}>
                <SelectTrigger className="w-full" id="locale">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pl">Polski</SelectItem>
                  <SelectItem value="en">English</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          )}
        />
      </FieldGroup>
      {problem && <Problem message={problem} />}
      <Button
        className="w-full"
        disabled={form.formState.isSubmitting}
        type="submit"
      >
        {form.formState.isSubmitting ? t("creating") : t("createAccount")}
      </Button>
      <p className="text-center text-sm text-muted-foreground">
        {t("haveAccount")}{" "}
        <Link className="text-primary hover:underline" href="/login">
          {t("signIn")}
        </Link>
      </p>
    </form>
  );
}

export function VerificationForm({ token }: { token?: string }) {
  const t = useTranslations("Identity");
  const [message, setMessage] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const validationSchema = useMemo(
    () => z.object({ email: emailSchema(t) }),
    [t],
  );
  const tokenForm = useForm<{ token: string }>({
    defaultValues: { token: token ?? "" },
  });
  const emailForm = useForm<EmailValues>({
    resolver: zodResolver(validationSchema),
  });
  async function confirm(values: { token: string }) {
    setProblem(undefined);
    try {
      await confirmEmailVerification(values.token);
      setMessage(t("emailConfirmed"));
    } catch (error) {
      setProblem(identityErrorMessage(error, problemMessages(t)));
    }
  }
  async function resend(values: EmailValues) {
    setProblem(undefined);
    try {
      setMessage(await requestEmailVerification(values.email));
    } catch (error) {
      setProblem(identityErrorMessage(error, problemMessages(t)));
    }
  }
  return (
    <div className="space-y-6">
      {message && <Notice>{message}</Notice>}
      <form className="space-y-4" onSubmit={tokenForm.handleSubmit(confirm)}>
        <TextField
          error={tokenForm.formState.errors.token?.message}
          label={t("verificationToken")}
          registration={tokenForm.register("token", {
            required: t("validationToken"),
          })}
        />
        <Button
          className="w-full"
          disabled={tokenForm.formState.isSubmitting}
          type="submit"
        >
          {t("confirmAddress")}
        </Button>
      </form>
      <div className="border-t pt-5">
        <form className="space-y-4" onSubmit={emailForm.handleSubmit(resend)}>
          <TextField
            error={emailForm.formState.errors.email?.message}
            label={t("resendToEmail")}
            registration={emailForm.register("email")}
            type="email"
          />
          <Button className="w-full" type="submit" variant="outline">
            {t("resend")}
          </Button>
        </form>
      </div>
      {problem && <Problem message={problem} />}
    </div>
  );
}

export function PasswordResetRequestForm() {
  const t = useTranslations("Identity");
  const [message, setMessage] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const validationSchema = useMemo(
    () => z.object({ email: emailSchema(t) }),
    [t],
  );
  const form = useForm<EmailValues>({
    resolver: zodResolver(validationSchema),
  });
  async function submit(values: EmailValues) {
    setProblem(undefined);
    try {
      setMessage(await requestPasswordReset(values));
    } catch (error) {
      setProblem(identityErrorMessage(error, problemMessages(t)));
    }
  }
  if (message) return <Notice>{message}</Notice>;
  return (
    <form className="space-y-5" onSubmit={form.handleSubmit(submit)}>
      <TextField
        autoComplete="email"
        error={form.formState.errors.email?.message}
        label={t("email")}
        registration={form.register("email")}
        type="email"
      />
      {problem && <Problem message={problem} />}
      <Button
        className="w-full"
        disabled={form.formState.isSubmitting}
        type="submit"
      >
        {t("sendInstructions")}
      </Button>
    </form>
  );
}

export function PasswordResetConfirmForm({ token }: { token?: string }) {
  const t = useTranslations("Identity");
  const [done, setDone] = useState(false);
  const [problem, setProblem] = useState<string>();
  const resetSchema = useMemo(() => {
    const password = passwordSchema(t);
    return z
      .object({ password, passwordRepeat: password })
      .refine((value) => value.password === value.passwordRepeat, {
        message: t("validationPasswordsMatch"),
        path: ["passwordRepeat"],
      });
  }, [t]);
  const form = useForm<ResetValues>({ resolver: zodResolver(resetSchema) });
  async function submit(values: ResetValues) {
    if (!token) {
      setProblem(t("missingResetToken"));
      return;
    }
    setProblem(undefined);
    try {
      await confirmPasswordReset({ token, password: values.password });
      setDone(true);
    } catch (error) {
      const passwordError = identityFieldError(error, "password");
      if (passwordError) {
        form.setError("password", { type: "server", message: passwordError });
      }
      setProblem(identityErrorMessage(error, problemMessages(t)));
    }
  }
  if (done)
    return (
      <Notice>
        {t("passwordChanged")}{" "}
        <Link className="underline" href="/login">
          {t("goToLogin")}
        </Link>
      </Notice>
    );
  return (
    <form className="space-y-5" onSubmit={form.handleSubmit(submit)}>
      <TextField
        autoComplete="new-password"
        error={form.formState.errors.password?.message}
        label={t("newPassword")}
        registration={form.register("password")}
        type="password"
      />
      <TextField
        autoComplete="new-password"
        error={form.formState.errors.passwordRepeat?.message}
        label={t("repeatPassword")}
        registration={form.register("passwordRepeat")}
        type="password"
      />
      {problem && <Problem message={problem} />}
      <Button
        className="w-full"
        disabled={form.formState.isSubmitting}
        type="submit"
      >
        {t("setNewPassword")}
      </Button>
    </form>
  );
}

function TextField({
  label,
  error,
  description,
  registration,
  ...inputProps
}: {
  label: string;
  error?: string;
  description?: string;
  registration: UseFormRegisterReturn;
} & ComponentProps<typeof Input>) {
  const id = registration.name;
  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        aria-invalid={Boolean(error)}
        id={id}
        {...registration}
        {...inputProps}
      />
      {description && <FieldDescription>{description}</FieldDescription>}
      <FieldError>{error}</FieldError>
    </Field>
  );
}

function Problem({ message }: { message: string }) {
  return (
    <div
      className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
      role="alert"
    >
      {message}
    </div>
  );
}

function Notice({ children }: { children: ReactNode }) {
  return (
    <div
      className="rounded-lg border border-primary/20 bg-primary/5 p-3 text-sm"
      role="status"
    >
      {children}
    </div>
  );
}
