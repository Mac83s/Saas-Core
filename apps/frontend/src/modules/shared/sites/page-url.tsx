"use client";

import { useEffect, useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRightIcon, LinkIcon, Trash2Icon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useForm, type SubmitHandler } from "react-hook-form";
import { z } from "zod";

import {
  changePageUrl,
  deleteSiteRedirect,
  listSiteRedirects,
  type PageUrlChangeInput,
  type SiteRedirect,
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
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { Textarea } from "@saas-core/ui/components/textarea";

import { sitesErrorMessage } from "./problem";

type UrlValues = { slug: string; reason: string };

/** The one deliberate way past the published-slug lock.
 *
 *  Deliberately a dialog rather than an editable field: the lock exists
 *  because every link and search result points at the published address, and
 *  the reason is stored because six months later the audit entry is the only
 *  thing that explains why a ranking address moved. */
export function PageUrlDialog({
  locale,
  onChanged,
  pageId,
  slug,
}: {
  locale: string;
  onChanged: () => Promise<void>;
  pageId: string;
  slug: string;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const schema = useMemo(
    () =>
      z.object({
        slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, t("invalidSlug")),
        reason: z.string().trim().min(1, t("changeUrlReasonRequired")),
      }),
    [t],
  );
  const form = useForm<UrlValues>({
    resolver: zodResolver(schema),
    defaultValues: { slug, reason: "" },
  });

  const submit: SubmitHandler<UrlValues> = async (values) => {
    setBusy(true);
    setProblem(undefined);
    try {
      // The editor carries the locale as a plain string; the contract
      // knows only the two the site can be published in.
      const contractLocale: PageUrlChangeInput["locale"] =
        locale === "en" ? "en" : "pl";
      await changePageUrl(pageId, { ...values, locale: contractLocale });
      await onChanged();
      form.reset({ slug: values.slug, reason: "" });
      setOpen(false);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setProblem(undefined);
          form.reset({ slug, reason: "" });
        }
      }}
      open={open}
    >
      <DialogTrigger
        render={<Button size="sm" type="button" variant="outline" />}
      >
        <LinkIcon aria-hidden="true" />
        {t("changeUrl")}
      </DialogTrigger>
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>{t("changeUrl")}</DialogTitle>
          <DialogDescription>{t("changeUrlDescription")}</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(event) => {
            void form.handleSubmit(submit)(event);
          }}
        >
          <Field>
            <FieldLabel htmlFor="page-url-slug">{t("slug")}</FieldLabel>
            <Input
              aria-invalid={Boolean(form.formState.errors.slug)}
              id="page-url-slug"
              {...form.register("slug")}
            />
            {form.formState.errors.slug && (
              <FieldError>{form.formState.errors.slug.message}</FieldError>
            )}
          </Field>
          <Field>
            <FieldLabel htmlFor="page-url-reason">
              {t("changeUrlReason")}
            </FieldLabel>
            <Textarea
              aria-invalid={Boolean(form.formState.errors.reason)}
              id="page-url-reason"
              rows={3}
              {...form.register("reason")}
            />
            {form.formState.errors.reason && (
              <FieldError>{form.formState.errors.reason.message}</FieldError>
            )}
          </Field>
          <p className="text-sm text-muted-foreground">
            {t("changeUrlPublishHint")}
          </p>
          {problem && (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          )}
          <DialogFooter>
            <Button disabled={busy} type="submit">
              {t("changeUrlSubmit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Every address this site used to answer on, and where it now points. */
export function SiteRedirectsCard({ siteId }: { siteId: string }) {
  const t = useTranslations("Sites");
  const [redirects, setRedirects] = useState<SiteRedirect[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  useEffect(() => {
    let mounted = true;
    void listSiteRedirects(siteId)
      .then((items) => {
        if (mounted) setRedirects(items);
      })
      .catch((error: unknown) => {
        if (mounted) setProblem(sitesErrorMessage(error, t));
      });
    return () => {
      mounted = false;
    };
  }, [siteId, t]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("redirects")}</CardTitle>
        <CardDescription>{t("redirectsDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        {problem && (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        )}
        {redirects.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("redirectsEmpty")}</p>
        ) : (
          <ul aria-describedby="redirects-hint" className="space-y-3">
            {redirects.map((redirect) => (
              <li className="space-y-1 rounded-lg border p-3" key={redirect.id}>
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <code className="break-all">{redirect.from_path}</code>
                  <ArrowRightIcon aria-hidden="true" className="size-4" />
                  <code className="break-all">{redirect.to_path}</code>
                  <Button
                    aria-label={t("redirectDelete", {
                      path: redirect.from_path,
                    })}
                    className="ms-auto"
                    disabled={busy}
                    onClick={() => {
                      setBusy(true);
                      setProblem(undefined);
                      void deleteSiteRedirect(redirect.id)
                        .then(() => {
                          setRedirects((current) =>
                            current.filter((item) => item.id !== redirect.id),
                          );
                        })
                        .catch((error: unknown) => {
                          setProblem(sitesErrorMessage(error, t));
                        })
                        .finally(() => {
                          setBusy(false);
                        });
                    }}
                    size="icon-sm"
                    type="button"
                    variant="ghost"
                  >
                    <Trash2Icon aria-hidden="true" />
                  </Button>
                </div>
                {redirect.reason && (
                  <p className="text-sm text-muted-foreground">
                    {redirect.reason}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
        {redirects.length > 0 && (
          <p className="mt-3 text-sm text-muted-foreground" id="redirects-hint">
            {t("redirectDeleteHint")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
