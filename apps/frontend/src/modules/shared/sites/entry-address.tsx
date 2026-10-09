"use client";

/** „Adres wpisu” (ADR-079 pkt 16): the last part of an entry's address, the
 *  former ones that lead to it, and changing it — checked with the server
 *  first, so the person sees what will redirect, whose redirect stops and
 *  that a draft's unpublished changes stay where they are, and only then
 *  confirms.
 *
 *  A company's panel shows whole addresses. The platform's own workspace has
 *  no site address to show — the product's pages put an entry's address
 *  together — so its panel shows the parts: type, language and slug. */

import { useEffect, useState } from "react";
import { LinkIcon } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  changeEntryAddress,
  getEntryAddress,
  previewEntryAddress,
  type ContentCollection,
  type ContentEntry,
  type EntryAddress as Address,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import { Checkbox } from "@saas-core/ui/components/checkbox";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { usePublisher } from "#components/panel/panel-access";

import { sitesErrorMessage } from "./problem";
import { useLanguageName } from "./term-list-panel";

const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** The last part of a path: what a publisher is shown instead of an address. */
function lastPart(path: string): string {
  return path.split("/").filter(Boolean).at(-1) ?? "";
}

export function EntryAddress({
  entry,
  collection,
  onChanged,
}: {
  entry: ContentEntry;
  collection: ContentCollection | undefined;
  onChanged: () => Promise<void>;
}) {
  const t = useTranslations("Sites");
  const publisher = usePublisher();
  const languageName = useLanguageName();
  const [address, setAddress] = useState<Address>();
  const [slug, setSlug] = useState("");
  // The server's answer is kept with the slug it is about: typing another
  // one makes it not apply, without clearing anything in an effect.
  const [checked, setChecked] = useState<{ slug: string; result: Address }>();
  const [reason, setReason] = useState("");
  const [takeOver, setTakeOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<"moved" | "changed">();
  const [problem, setProblem] = useState<string>();
  const [reasonMissing, setReasonMissing] = useState(false);

  useEffect(() => {
    let current = true;
    getEntryAddress(entry.id)
      .then((result) => {
        if (current) setAddress(result);
      })
      .catch((error: unknown) => {
        if (current) setProblem(sitesErrorMessage(error, t));
      });
    return () => {
      current = false;
    };
  }, [entry.id, entry.slug, t]);

  const wanted = slug.trim().toLowerCase();
  const preview = checked?.slug === wanted ? checked.result : undefined;
  const invalid = wanted !== "" && !SLUG.test(wanted);

  async function check() {
    setProblem(undefined);
    setSaved(undefined);
    setBusy(true);
    try {
      const result = await previewEntryAddress(entry.id, {
        slug: wanted,
        reason: "",
        take_over_former: false,
      });
      setChecked({ slug: wanted, result });
      setTakeOver(false);
      setReasonMissing(false);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!preview) return;
    if (preview.moved.length > 0 && reason.trim() === "") {
      setReasonMissing(true);
      return;
    }
    setProblem(undefined);
    setBusy(true);
    try {
      const result = await changeEntryAddress(entry.id, {
        slug: wanted,
        reason: reason.trim(),
        take_over_former: takeOver,
      });
      setAddress({ ...result, previous_slug: result.slug, changed: false });
      setSaved(result.moved.length > 0 ? "moved" : "changed");
      setChecked(undefined);
      setSlug("");
      setReason("");
      await onChanged();
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setBusy(false);
    }
  }

  const id = (field: string) => `entry-address-${field}-${entry.id}`;
  const shown = (path: string) => (publisher ? lastPart(path) : path);
  return (
    <section
      aria-labelledby={id("heading")}
      className="space-y-3 rounded-lg border p-4"
    >
      <div className="flex items-center gap-2">
        <LinkIcon aria-hidden="true" className="size-4" />
        <h3 className="font-medium" id={id("heading")}>
          {t("entryAddress.title")}
        </h3>
      </div>
      {address === undefined && !problem ? (
        <p className="text-sm text-muted-foreground">
          {t("entryAddress.loading")}
        </p>
      ) : null}
      {address ? (
        <div className="space-y-2 text-sm">
          {publisher ? (
            <>
              <p>
                {t("entryAddress.parts", {
                  type: collection?.name ?? "",
                  language: languageName(address.locale),
                  slug: address.slug,
                })}
              </p>
              <p className="text-muted-foreground">
                {t("entryAddress.partsHint")}
              </p>
            </>
          ) : (
            <p>
              {t(
                address.published
                  ? "entryAddress.current"
                  : "entryAddress.currentDraft",
                { path: address.path },
              )}
            </p>
          )}
          {address.redirects.length > 0 ? (
            <div>
              <p>
                {t(
                  publisher
                    ? "entryAddress.formerSlugs"
                    : "entryAddress.former",
                )}
              </p>
              <ul className="list-disc pl-5">
                {address.redirects.map((item) => (
                  <li key={item.from_path}>
                    <code>{shown(item.from_path)}</code>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
      <Field>
        <FieldLabel htmlFor={id("slug")}>{t("entryAddress.slug")}</FieldLabel>
        <Input
          aria-describedby={id("slug-hint")}
          aria-invalid={invalid}
          autoCapitalize="none"
          autoComplete="off"
          id={id("slug")}
          onChange={(event) => {
            setSlug(event.target.value);
            setSaved(undefined);
          }}
          spellCheck={false}
          value={slug}
        />
        {invalid ? (
          <FieldError>{t("entryAddress.errors.invalid")}</FieldError>
        ) : (
          <FieldDescription id={id("slug-hint")}>
            {t("entryAddress.slugHint")}
          </FieldDescription>
        )}
      </Field>
      {preview === undefined ? (
        <Button
          disabled={busy || wanted === "" || invalid}
          onClick={() => void check()}
          size="sm"
          type="button"
          variant="outline"
        >
          {t("entryAddress.check")}
        </Button>
      ) : null}
      {preview && !preview.changed ? (
        <p className="text-sm text-muted-foreground" role="status">
          {t("entryAddress.same")}
        </p>
      ) : null}
      {preview?.changed ? (
        <div
          aria-label={t("entryAddress.check")}
          className="space-y-3 rounded-md bg-muted p-3 text-sm"
          role="group"
        >
          <p className="font-medium">
            {publisher
              ? t("entryAddress.newSlug", { slug: preview.slug })
              : t("entryAddress.newPath", { path: preview.path })}
          </p>
          {preview.published ? (
            <p>{t("entryAddress.republish")}</p>
          ) : preview.redirects.length === 0 ? (
            <p>{t("entryAddress.freeChange")}</p>
          ) : null}
          {preview.published && preview.unpublished_changes ? (
            <p>{t("entryAddress.unpublishedChanges")}</p>
          ) : null}
          {preview.redirects.length > 0 ? (
            <div>
              <p>{t("entryAddress.willRedirect")}</p>
              <ul className="list-disc pl-5">
                {preview.redirects.map((item) => (
                  <li key={item.from_path}>
                    <code>{shown(item.from_path)}</code>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {preview.takes_over.map((taken) => (
            <p key={taken.entry_id}>
              {t("entryAddress.takesOver", { title: taken.title })}
            </p>
          ))}
          {preview.takes_over.length > 0 ? (
            <label className="flex min-h-11 items-center gap-3">
              <Checkbox
                checked={takeOver}
                onCheckedChange={(value) => setTakeOver(value === true)}
              />
              {t("entryAddress.takeOver")}
            </label>
          ) : null}
          {preview.moved.length > 0 ? (
            <Field>
              <FieldLabel htmlFor={id("reason")}>
                {t("entryAddress.reason")}
              </FieldLabel>
              <Input
                aria-describedby={id("reason-hint")}
                aria-invalid={reasonMissing}
                id={id("reason")}
                maxLength={500}
                onChange={(event) => {
                  setReason(event.target.value);
                  setReasonMissing(false);
                }}
                value={reason}
              />
              {reasonMissing ? (
                <FieldError>{t("entryAddress.reasonRequired")}</FieldError>
              ) : (
                <FieldDescription id={id("reason-hint")}>
                  {t("entryAddress.reasonHint")}
                </FieldDescription>
              )}
            </Field>
          ) : null}
          <Button
            disabled={busy || (preview.takes_over.length > 0 && !takeOver)}
            onClick={() => void confirm()}
            size="sm"
            type="button"
          >
            {t("entryAddress.confirm")}
          </Button>
        </div>
      ) : null}
      {saved && !problem ? (
        <p className="text-sm text-muted-foreground" role="status">
          {t(
            saved === "moved"
              ? "entryAddress.saved"
              : "entryAddress.savedDraft",
          )}
        </p>
      ) : null}
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
    </section>
  );
}
