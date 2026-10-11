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
  completeMfaLogin,
  confirmEmailVerification,
  confirmPasswordReset,
  loginAccount,
  registerAccount,
  requestEmailVerification,
  requestPasswordReset,
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
  InputOTP,
  InputOTPGroup,
  InputOTPSlot,
} from "@saas-core/ui/components/input-otp";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@saas-core/ui/components/select";

import { Link, useRouter } from "#i18n/navigation";
import { registrationHref } from "#lib/sign-up";
import { TwoFactorCard } from "./account-security";
import { identityErrorMessage, identityFieldError } from "./problem";
import { AuthShell } from "./auth-shell";

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
    mfaLocked: t("mfaLocked"),
    apiUnavailable: t("apiUnavailable"),
  };
}

/**
 * The whole sign-in screen: the shell's header follows the step. While an
 * operator sets the first factor the form is no longer about e-mail and
 * password, so its heading says so.
 */
export function LoginScreen({ returnTo = "/panel" }: { returnTo?: string }) {
  const t = useTranslations("Identity");
  const [setup, setSetup] = useState(false);
  return (
    <AuthShell
      title={t(setup ? "loginSetupTitle" : "loginTitle")}
      description={t(setup ? "loginSetupDescription" : "loginDescription")}
    >
      <LoginForm onSetupChange={setSetup} returnTo={returnTo} />
    </AuthShell>
  );
}

export function LoginForm({
  returnTo = "/panel",
  onSetupChange,
}: {
  returnTo?: string;
  /** Told when the first-factor set-up step opens, so the screen can retitle. */
  onSetupChange?: (setup: boolean) => void;
}) {
  const t = useTranslations("Identity");
  const router = useRouter();
  const [stage, setStage] = useState<"password" | "mfa" | "setup">("password");
  const [problem, setProblem] = useState<string>();
  // The second step takes the six digits of the app, or — behind a text
  // button — a recovery code (not six digits). Both travel as `code`.
  const [recovery, setRecovery] = useState(false);
  const register = registrationHref(returnTo);
  const loginSchema = useMemo(
    () =>
      z.object({
        email: emailSchema(t),
        password: z.string().min(1, t("validationPasswordRequired")),
      }),
    [t],
  );
  const codeSchema = useMemo(
    () =>
      z.object({
        code: recovery
          ? z.string().min(6, t("validationCode"))
          : z.string().regex(/^\d{6}$/, t("validationAppCode")),
      }),
    [t, recovery],
  );
  const form = useForm<LoginValues>({ resolver: zodResolver(loginSchema) });
  const codeForm = useForm<CodeValues>({
    resolver: zodResolver(codeSchema),
    defaultValues: { code: "" },
  });

  function switchCodeKind() {
    setRecovery((current) => !current);
    setProblem(undefined);
    codeForm.reset({ code: "" });
  }

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
      // An operator's first MFA is set on the server, never here with a
      // password alone (platform settings 0c): `mfa_setup_required` is shown
      // as its message. A stack with `OPERATOR_MFA_SETUP_AT_LOGIN` on answers `mfa_setup_at_login` instead
      // and the QR code is set up right here.
      if (
        error instanceof ApiProblemError &&
        error.problem.code === "mfa_setup_at_login"
      ) {
        setStage("setup");
        onSetupChange?.(true);
        return;
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

  if (stage === "setup") {
    return (
      <TwoFactorCard
        onDone={() => {
          router.replace(returnTo);
          router.refresh();
        }}
      />
    );
  }

  if (stage !== "password") {
    return (
      <form className="space-y-5" onSubmit={codeForm.handleSubmit(submitCode)}>
        <Controller
          control={codeForm.control}
          name="code"
          render={({ field }) => {
            const message = codeForm.formState.errors.code?.message;
            const id = "mfa-login-code";
            // A wrong code comes back as the problem box below, not as a
            // field error; both mark the field and are read with it.
            const invalid = Boolean(message) || Boolean(problem);
            const describedBy = message
              ? `${id}-error`
              : problem
                ? "mfa-login-problem"
                : undefined;
            return (
              <Field data-invalid={invalid}>
                <FieldLabel htmlFor={id}>
                  {t(recovery ? "recoveryCodeLabel" : "mfaCodeLabel")}
                </FieldLabel>
                {recovery ? (
                  <Input
                    aria-describedby={describedBy}
                    aria-invalid={invalid}
                    autoCapitalize="none"
                    autoComplete="off"
                    autoFocus
                    id={id}
                    name={field.name}
                    onBlur={field.onBlur}
                    onChange={field.onChange}
                    ref={field.ref}
                    spellCheck={false}
                    value={field.value}
                  />
                ) : (
                  <InputOTP
                    aria-describedby={describedBy}
                    aria-invalid={invalid}
                    autoFocus
                    id={id}
                    name={field.name}
                    onBlur={field.onBlur}
                    onChange={field.onChange}
                    ref={field.ref}
                    value={field.value}
                  >
                    <InputOTPGroup>
                      {[0, 1, 2, 3, 4, 5].map((index) => (
                        <InputOTPSlot index={index} key={index} />
                      ))}
                    </InputOTPGroup>
                  </InputOTP>
                )}
                <FieldError id={`${id}-error`}>{message}</FieldError>
              </Field>
            );
          }}
        />
        {problem && <Problem id="mfa-login-problem" message={problem} />}
        <Button
          className="w-full"
          disabled={codeForm.formState.isSubmitting}
          type="submit"
        >
          {codeForm.formState.isSubmitting
            ? t("checking")
            : t("confirmAndSignIn")}
        </Button>
        <Button
          className="w-full"
          onClick={switchCodeKind}
          type="button"
          variant="link"
        >
          {t(recovery ? "useAppCode" : "useRecoveryCode")}
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
        {/* Not where nobody may sign up by themselves (`registrationHref`). */}
        {register ? (
          <Link className="text-primary hover:underline" href={register}>
            {t("createAccount")}
          </Link>
        ) : null}
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
  // Registration answers the same way whether or not the account is new, so
  // the screen that follows says only "check your inbox" — and links to the
  // place that can send the message again.
  if (message)
    return (
      <div className="space-y-4">
        <Notice>{message}</Notice>
        <p className="text-sm text-muted-foreground">
          {t("pendingHint")}{" "}
          <Link className="text-primary hover:underline" href="/verify-email">
            {t("pendingLink")}
          </Link>
        </p>
      </div>
    );
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
              <Select
                // The trigger shows the option's label, not its raw value,
                // before the list has ever been opened.
                items={[
                  { value: "pl", label: "Polski" },
                  { value: "en", label: "English" },
                ]}
                onValueChange={field.onChange}
                value={field.value}
              >
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
  const confirmForm = (
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
  );
  const resendForm = (
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
  );
  // Arriving from the link in the message, confirming is the one thing to do.
  // Arriving without it, the account is simply waiting: say so, offer another
  // message, and keep pasting a code as the way out when none arrives.
  return (
    <div className="space-y-6">
      {message && <Notice>{message}</Notice>}
      {token ? (
        <>
          {confirmForm}
          <div className="border-t pt-5">{resendForm}</div>
        </>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">{t("pendingBody")}</p>
          {resendForm}
          <div className="space-y-3 border-t pt-5">
            <h2 className="text-sm font-medium">{t("haveCode")}</h2>
            {confirmForm}
          </div>
        </>
      )}
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

function Problem({ id, message }: { id?: string; message: string }) {
  return (
    <div
      id={id}
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
