"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  getCurrentUser,
  updateCurrentUser,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

type Values = { first_name: string; last_name: string };

/** The person's own name: how the panel greets them and shows them to a team. */
export function ProfileNameForm() {
  const t = useTranslations("AccountSettings");
  const identity = useTranslations("Identity");
  const [saved, setSaved] = useState(false);
  const schema = useMemo(
    () =>
      z.object({
        first_name: z.string().trim().max(80),
        last_name: z.string().trim().max(80),
      }),
    [],
  );
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { first_name: "", last_name: "" },
  });
  const { reset, setError } = form;
  const problem = (error: unknown) =>
    error instanceof ApiProblemError
      ? error.message
      : identity("apiUnavailable");

  useEffect(() => {
    getCurrentUser()
      .then((user) =>
        reset({ first_name: user.first_name, last_name: user.last_name }),
      )
      .catch((error: unknown) =>
        setError("root", {
          type: "server",
          message:
            error instanceof ApiProblemError
              ? error.message
              : identity("apiUnavailable"),
        }),
      );
  }, [identity, reset, setError]);

  async function submit(values: Values) {
    setSaved(false);
    try {
      const user = await updateCurrentUser(values);
      reset({ first_name: user.first_name, last_name: user.last_name });
      setSaved(true);
    } catch (error) {
      setError("root", { type: "server", message: problem(error) });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("nameTitle")}</CardTitle>
        <CardDescription>{t("nameDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-4"
          noValidate
          onSubmit={form.handleSubmit(submit)}
        >
          <FieldGroup className="grid gap-4 sm:grid-cols-2">
            {(["first_name", "last_name"] as const).map((name) => (
              <Field
                data-invalid={Boolean(form.formState.errors[name])}
                key={name}
              >
                <FieldLabel htmlFor={`profile-${name}`}>{t(name)}</FieldLabel>
                <Input
                  autoComplete={
                    name === "first_name" ? "given-name" : "family-name"
                  }
                  id={`profile-${name}`}
                  {...form.register(name)}
                />
                <FieldError errors={[form.formState.errors[name]]} />
              </Field>
            ))}
          </FieldGroup>
          {form.formState.errors.root ? (
            <p className="text-sm text-destructive" role="alert">
              {form.formState.errors.root.message}
            </p>
          ) : null}
          {saved ? (
            <p className="text-sm text-muted-foreground" role="status">
              {t("nameSaved")}
            </p>
          ) : null}
          <Button disabled={form.formState.isSubmitting} type="submit">
            {t("nameSave")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
