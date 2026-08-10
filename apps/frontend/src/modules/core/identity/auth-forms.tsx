"use client";

import { useState } from "react";
import type { ComponentProps, ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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

import { identityErrorMessage, identityFieldError } from "./problem";

const email = z.string().email("Podaj prawidłowy adres e-mail.");
const password = z.string().min(12, "Hasło musi mieć co najmniej 12 znaków.");
const loginSchema = z.object({
  email,
  password: z.string().min(1, "Podaj hasło."),
});
const registrationSchema = z.object({
  email,
  password,
  locale: z.enum(["pl", "en"]),
});
const codeSchema = z.object({
  code: z.string().min(6, "Podaj kod z aplikacji lub kod odzyskiwania."),
});
const emailSchema = z.object({ email });
const resetSchema = z
  .object({ password, passwordRepeat: password })
  .refine((value) => value.password === value.passwordRepeat, {
    message: "Hasła muszą być identyczne.",
    path: ["passwordRepeat"],
  });

type LoginValues = z.infer<typeof loginSchema>;
type RegistrationValues = z.infer<typeof registrationSchema>;
type CodeValues = z.infer<typeof codeSchema>;
type EmailValues = z.infer<typeof emailSchema>;
type ResetValues = z.infer<typeof resetSchema>;

export function LoginForm() {
  const router = useRouter();
  const [stage, setStage] = useState<"password" | "mfa" | "setup">("password");
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [problem, setProblem] = useState<string>();
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
      router.replace("/panel");
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
          setProblem(identityErrorMessage(setupError));
          return;
        }
      }
      const emailError = identityFieldError(error, "email");
      const passwordError = identityFieldError(error, "password");
      if (emailError)
        form.setError("email", { type: "server", message: emailError });
      if (passwordError)
        form.setError("password", { type: "server", message: passwordError });
      setProblem(identityErrorMessage(error));
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
      router.replace("/panel");
      router.refresh();
    } catch (error) {
      const codeError = identityFieldError(error, "code");
      if (codeError)
        codeForm.setError("code", { type: "server", message: codeError });
      setProblem(identityErrorMessage(error));
    }
  }

  if (recoveryCodes.length > 0) {
    return (
      <div className="space-y-4">
        <Notice>Skopiuj kody odzyskiwania. Nie pokażemy ich ponownie.</Notice>
        <ul className="grid grid-cols-2 gap-2 rounded-lg border bg-muted/40 p-3 font-mono text-xs">
          {recoveryCodes.map((code) => (
            <li key={code}>{code}</li>
          ))}
        </ul>
        <Button className="w-full" onClick={() => router.replace("/panel")}>
          Kody zapisane — przejdź do panelu
        </Button>
      </div>
    );
  }

  if (stage !== "password") {
    return (
      <form className="space-y-5" onSubmit={codeForm.handleSubmit(submitCode)}>
        {stage === "setup" && setup && (
          <div className="space-y-3">
            <Notice>
              Dodaj konto w aplikacji uwierzytelniającej, a następnie wpisz kod.
            </Notice>
            <div className="rounded-lg border bg-muted/40 p-3 text-xs break-all">
              <p className="font-medium">Sekret ręczny</p>
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
            stage === "setup"
              ? "Kod potwierdzający"
              : "Kod MFA lub odzyskiwania"
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
            ? "Sprawdzanie…"
            : "Potwierdź i zaloguj"}
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
          label="E-mail"
          registration={form.register("email")}
          type="email"
        />
        <TextField
          autoComplete="current-password"
          error={form.formState.errors.password?.message}
          label="Hasło"
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
        {form.formState.isSubmitting ? "Logowanie…" : "Zaloguj się"}
      </Button>
      <div className="flex justify-between text-sm">
        <Link className="text-primary hover:underline" href="/password-reset">
          Nie pamiętam hasła
        </Link>
        <Link className="text-primary hover:underline" href="/register">
          Utwórz konto
        </Link>
      </div>
    </form>
  );
}

export function RegistrationForm() {
  const [message, setMessage] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const form = useForm<RegistrationValues>({
    resolver: zodResolver(registrationSchema),
    defaultValues: { locale: "pl" },
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
      setProblem(identityErrorMessage(error));
    }
  }
  if (message) return <Notice>{message}</Notice>;
  return (
    <form className="space-y-5" onSubmit={form.handleSubmit(submit)}>
      <FieldGroup>
        <TextField
          autoComplete="email"
          error={form.formState.errors.email?.message}
          label="E-mail"
          registration={form.register("email")}
          type="email"
        />
        <TextField
          autoComplete="new-password"
          description="Minimum 12 znaków; użyj unikalnego hasła."
          error={form.formState.errors.password?.message}
          label="Hasło"
          registration={form.register("password")}
          type="password"
        />
        <Controller
          control={form.control}
          name="locale"
          render={({ field }) => (
            <Field>
              <FieldLabel htmlFor="locale">Język komunikacji</FieldLabel>
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
        {form.formState.isSubmitting ? "Tworzenie…" : "Utwórz konto"}
      </Button>
      <p className="text-center text-sm text-muted-foreground">
        Masz konto?{" "}
        <Link className="text-primary hover:underline" href="/login">
          Zaloguj się
        </Link>
      </p>
    </form>
  );
}

export function VerificationForm({ token }: { token?: string }) {
  const [message, setMessage] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const tokenForm = useForm<{ token: string }>({
    defaultValues: { token: token ?? "" },
  });
  const emailForm = useForm<EmailValues>({
    resolver: zodResolver(emailSchema),
  });
  async function confirm(values: { token: string }) {
    setProblem(undefined);
    try {
      await confirmEmailVerification(values.token);
      setMessage("Adres e-mail został potwierdzony. Możesz się zalogować.");
    } catch (error) {
      setProblem(identityErrorMessage(error));
    }
  }
  async function resend(values: EmailValues) {
    setProblem(undefined);
    try {
      setMessage(await requestEmailVerification(values.email));
    } catch (error) {
      setProblem(identityErrorMessage(error));
    }
  }
  return (
    <div className="space-y-6">
      {message && <Notice>{message}</Notice>}
      <form className="space-y-4" onSubmit={tokenForm.handleSubmit(confirm)}>
        <TextField
          error={tokenForm.formState.errors.token?.message}
          label="Token weryfikacyjny"
          registration={tokenForm.register("token", {
            required: "Podaj token.",
          })}
        />
        <Button
          className="w-full"
          disabled={tokenForm.formState.isSubmitting}
          type="submit"
        >
          Potwierdź adres
        </Button>
      </form>
      <div className="border-t pt-5">
        <form className="space-y-4" onSubmit={emailForm.handleSubmit(resend)}>
          <TextField
            error={emailForm.formState.errors.email?.message}
            label="Wyślij ponownie na e-mail"
            registration={emailForm.register("email")}
            type="email"
          />
          <Button className="w-full" type="submit" variant="outline">
            Wyślij ponownie
          </Button>
        </form>
      </div>
      {problem && <Problem message={problem} />}
    </div>
  );
}

export function PasswordResetRequestForm() {
  const [message, setMessage] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const form = useForm<EmailValues>({ resolver: zodResolver(emailSchema) });
  async function submit(values: EmailValues) {
    setProblem(undefined);
    try {
      setMessage(await requestPasswordReset(values));
    } catch (error) {
      setProblem(identityErrorMessage(error));
    }
  }
  if (message) return <Notice>{message}</Notice>;
  return (
    <form className="space-y-5" onSubmit={form.handleSubmit(submit)}>
      <TextField
        autoComplete="email"
        error={form.formState.errors.email?.message}
        label="E-mail"
        registration={form.register("email")}
        type="email"
      />
      {problem && <Problem message={problem} />}
      <Button
        className="w-full"
        disabled={form.formState.isSubmitting}
        type="submit"
      >
        Wyślij instrukcję
      </Button>
    </form>
  );
}

export function PasswordResetConfirmForm({ token }: { token?: string }) {
  const [done, setDone] = useState(false);
  const [problem, setProblem] = useState<string>();
  const form = useForm<ResetValues>({ resolver: zodResolver(resetSchema) });
  async function submit(values: ResetValues) {
    if (!token) {
      setProblem("Brakuje tokenu resetu w adresie strony.");
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
      setProblem(identityErrorMessage(error));
    }
  }
  if (done)
    return (
      <Notice>
        Hasło zostało zmienione.{" "}
        <Link className="underline" href="/login">
          Przejdź do logowania.
        </Link>
      </Notice>
    );
  return (
    <form className="space-y-5" onSubmit={form.handleSubmit(submit)}>
      <TextField
        autoComplete="new-password"
        error={form.formState.errors.password?.message}
        label="Nowe hasło"
        registration={form.register("password")}
        type="password"
      />
      <TextField
        autoComplete="new-password"
        error={form.formState.errors.passwordRepeat?.message}
        label="Powtórz hasło"
        registration={form.register("passwordRepeat")}
        type="password"
      />
      {problem && <Problem message={problem} />}
      <Button
        className="w-full"
        disabled={form.formState.isSubmitting}
        type="submit"
      >
        Ustaw nowe hasło
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
