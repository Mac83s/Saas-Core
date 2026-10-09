"use client";

import { useRef, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRightIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useForm, type SubmitHandler } from "react-hook-form";
import { z } from "zod";

import { createSite, type SiteSummary } from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { mutationKey, type MutationReceipt } from "./idempotency";
import { sitesErrorMessage } from "./problem";

/** The languages a site's record can start in: the API's own list
 *  (`locale_not_seeded` for any other), as in a company's first steps. */
const LANGUAGES = ["pl", "en"] as const;

type Values = { default_locale: (typeof LANGUAGES)[number] };

/**
 * The first step of the platform's own workspace, in place of a company's
 * site wizard (ADR-079 pkt 29). Its content hangs on a site's record, but no
 * host serves that site: so nothing here asks for an address or a name
 * nobody would read — only for the language the content is written in, the
 * one thing of that record the content depends on and that cannot be changed
 * afterwards. The record gets its platform address from the API unasked.
 */
export function PublisherStart({
  onCompleted,
}: {
  onCompleted: (site: SiteSummary) => void | Promise<void>;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const receipt = useRef<MutationReceipt | undefined>(undefined);
  const [problem, setProblem] = useState<string>();
  const form = useForm<Values>({
    resolver: zodResolver(z.object({ default_locale: z.enum(LANGUAGES) })),
    defaultValues: { default_locale: "pl" },
  });

  const submit: SubmitHandler<Values> = async ({ default_locale }) => {
    setProblem(undefined);
    const input = {
      name: t("publisherStart.siteName"),
      slug: "content",
      default_locale,
    };
    try {
      const created = await createSite(
        input,
        mutationKey(receipt, "publisher-start", input),
      );
      receipt.current = undefined;
      await onCompleted(created);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-2xl">
          <h2>{t("publisherStart.title")}</h2>
        </CardTitle>
        <CardDescription>{t("publisherStart.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="max-w-sm space-y-5"
          onSubmit={form.handleSubmit(submit)}
        >
          <Field>
            <FieldLabel htmlFor="publisher-start-language">
              {t("publisherStart.language")}
            </FieldLabel>
            <NativeSelect
              id="publisher-start-language"
              {...form.register("default_locale")}
            >
              <option value="pl">{common("polish")}</option>
              <option value="en">{common("english")}</option>
            </NativeSelect>
          </Field>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <Button disabled={form.formState.isSubmitting} type="submit">
            {t("publisherStart.action")}
            <ArrowRightIcon aria-hidden="true" />
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
