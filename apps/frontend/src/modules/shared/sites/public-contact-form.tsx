"use client";

import { useId, useMemo, useRef, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  submitPublicSiteInquiry,
} from "@saas-core/api-client";
import {
  contactFormFields,
  siteUiTexts,
  type ContactFormMode,
} from "@saas-core/site-blocks";
import { Button } from "@saas-core/ui/components/button";
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { Textarea } from "@saas-core/ui/components/textarea";

// The server applies the same check (inquiry_serializers.py).
const PHONE = /^\+?[\d\s().\/-]+$/;
const validPhone = (value: string) =>
  PHONE.test(value) && /^(\D*\d){6,15}\D*$/.test(value);

const MAX = { name: 120, email: 254, phone: 32, message: 5000 } as const;

type Values = {
  name: string;
  email: string;
  phone: string;
  message: string;
  website: string;
};

export function PublicContactForm({
  path,
  blockPosition,
  publicationId,
  locale,
  contact,
  submitLabel,
  successMessage,
}: {
  path: string;
  blockPosition: number;
  publicationId: string;
  /** The page's language; its texts come from the site's catalogue. */
  locale: string;
  /** What the block's variant asks for; the server checks the same rules. */
  contact?: ContactFormMode;
  submitLabel?: string;
  successMessage?: string;
}) {
  const copy = siteUiTexts(locale).contactForm;
  const id = useId();
  const fields = useMemo(() => contactFormFields({ contact }), [contact]);
  const schema = useMemo(() => {
    const required = (field: keyof typeof MAX) =>
      fields.some(
        (entry) => entry.field === field && entry.rule === "required",
      );
    const text = (field: keyof typeof MAX) => {
      const value = z.string().trim().max(MAX[field], copy.tooLong);
      return required(field) ? value.min(1, copy.required) : value;
    };
    return z.object({
      name: text("name"),
      email: text("email").refine(
        (value) => !value || z.email().safeParse(value).success,
        copy.invalidEmail,
      ),
      phone: text("phone").refine(
        (value) => !value || validPhone(value),
        copy.invalidPhone,
      ),
      message: text("message"),
      website: z.string().max(200, copy.tooLong),
    });
  }, [copy, fields]);
  const { register, handleSubmit, formState } = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", email: "", phone: "", message: "", website: "" },
  });
  const [failure, setFailure] = useState<string>();
  const [accepted, setAccepted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const inFlight = useRef(false);
  // A failed response may follow an accepted request. Retrying the same content
  // must use the same key, even if the visitor edited it and then changed back.
  const attempts = useRef(new Map<string, string>());

  async function submit(values: Values) {
    if (inFlight.current || accepted) return;
    inFlight.current = true;
    setSubmitting(true);
    setFailure(undefined);
    const input = {
      path,
      publication_id: publicationId,
      block_position: blockPosition,
      name: values.name,
      email: values.email,
      phone: values.phone,
      message: values.message,
      website: values.website,
    };
    const fingerprint = JSON.stringify(input);
    let key = attempts.current.get(fingerprint);
    if (!key) {
      key = crypto.randomUUID();
      attempts.current.set(fingerprint, key);
    }
    try {
      const result = await submitPublicSiteInquiry(input, key);
      if (!result.accepted) throw new Error("Submission was not accepted");
      setAccepted(true);
    } catch (error) {
      const status =
        error instanceof ApiProblemError ? error.problem.status : 0;
      setFailure(
        status === 429
          ? copy.limited
          : status === 403 || status === 404
            ? copy.unavailable
            : status === 400
              ? copy.invalid
              : status === 409
                ? copy.conflict
                : status === 413
                  ? copy.tooLarge
                  : copy.error,
      );
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }

  return (
    <form
      aria-label={submitLabel || copy.submit}
      aria-busy={submitting}
      className="site-contact-form"
      method="post"
      noValidate
      onSubmit={(event) => void handleSubmit(submit)(event)}
    >
      {accepted ? (
        <p className="rounded-lg border border-current/20 p-4" role="status">
          {successMessage || copy.success}
        </p>
      ) : (
        <>
          <fieldset
            className="site-contact-form__fields min-w-0"
            disabled={submitting}
          >
            {fields.map(({ field, rule }) => {
              const error = formState.errors[field];
              const common = {
                ...register(field),
                "aria-describedby": error ? `${id}-${field}-error` : undefined,
                "aria-invalid": Boolean(error),
                id: `${id}-${field}`,
                maxLength: MAX[field],
                required: rule === "required",
              };
              return (
                <Field
                  className="site-contact-form__field"
                  key={field}
                  data-invalid={Boolean(error)}
                >
                  <FieldLabel htmlFor={`${id}-${field}`}>
                    {rule === "optional"
                      ? `${copy[field]} ${copy.optional}`
                      : copy[field]}
                  </FieldLabel>
                  {field === "message" ? (
                    <Textarea
                      {...common}
                      className="site-contact-input min-h-32"
                      rows={5}
                    />
                  ) : (
                    <Input
                      {...common}
                      autoComplete={field === "phone" ? "tel" : field}
                      className="site-contact-input"
                      type={
                        field === "email"
                          ? "email"
                          : field === "phone"
                            ? "tel"
                            : "text"
                      }
                    />
                  )}
                  {error ? (
                    <FieldError
                      className="site-contact-form__error"
                      id={`${id}-${field}-error`}
                    >
                      {error.message}
                    </FieldError>
                  ) : null}
                </Field>
              );
            })}
            <div aria-hidden="true" hidden>
              <label htmlFor={`${id}-website`}>Website</label>
              <input
                {...register("website")}
                autoComplete="off"
                id={`${id}-website`}
                tabIndex={-1}
                type="text"
              />
            </div>
            <Button className="site-section__action" type="submit">
              {submitting ? copy.submitting : submitLabel || copy.submit}
            </Button>
          </fieldset>
          {failure ? (
            <p
              className="site-contact-form__error text-sm text-destructive"
              role="alert"
            >
              {failure}
            </p>
          ) : null}
          {submitting ? (
            <p className="sr-only" role="status">
              {copy.submitting}
            </p>
          ) : null}
        </>
      )}
    </form>
  );
}
