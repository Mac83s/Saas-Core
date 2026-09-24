import { createElement } from "react";
import { renderImage } from "./ai-badge";
import { plainBlockText } from "./block-text";
import type {
  BlockComponentProps,
  ContactFieldRule,
  ContactFormMode,
  ContactFormV2Data,
} from "./types";

/** What each variant asks for (owner's decision of 24.09). The server
 *  applies the same table to the published block when a message arrives;
 *  the name is always required. */
export const CONTACT_FORM_FIELDS: Readonly<
  Record<
    ContactFormMode,
    {
      email: ContactFieldRule;
      phone: ContactFieldRule;
      message: ContactFieldRule;
    }
  >
> = {
  email: { email: "required", phone: "optional", message: "required" },
  callback: { email: "optional", phone: "required", message: "optional" },
  full: { email: "required", phone: "required", message: "required" },
  email_only: { email: "required", phone: "hidden", message: "required" },
};

/** The fields a form shows, in order: a call-back form asks for the phone
 *  before the e-mail. */
export function contactFormFields(
  data: Pick<ContactFormV2Data, "contact">,
): { field: "name" | "email" | "phone" | "message"; rule: ContactFieldRule }[] {
  const mode = data.contact ?? "email";
  const rules = CONTACT_FORM_FIELDS[mode];
  const contact: ("email" | "phone")[] =
    mode === "callback" ? ["phone", "email"] : ["email", "phone"];
  return [
    { field: "name" as const, rule: "required" as const },
    ...contact.map((field) => ({ field, rule: rules[field] })),
    { field: "message" as const, rule: rules.message },
  ].filter(({ rule }) => rule !== "hidden");
}

const LABELS = {
  pl: {
    name: "Imię",
    email: "E-mail",
    phone: "Telefon",
    message: "Wiadomość",
    optional: "(opcjonalnie)",
  },
  en: {
    name: "Name",
    email: "Email",
    phone: "Phone",
    message: "Message",
    optional: "(optional)",
  },
} as const;
const KINDS = {
  name: "text",
  email: "email",
  phone: "tel",
  message: "textarea",
} as const;

/** The catalogue/editor show a disabled fieldset; only a publication supplies
 * the application form adapter with its immutable publication and position. */
export function ContactFormSection({
  data,
  editor,
  imageRenderer,
  formRenderer,
}: BlockComponentProps) {
  const form = data as ContactFormV2Data;
  const text = editor?.text ?? plainBlockText;
  const en = form.locale === "en";
  const labels = LABELS[en ? "en" : "pl"];
  const fields = contactFormFields(form).map(({ field, rule }) => [
    rule === "optional" ? `${labels[field]} ${labels.optional}` : labels[field],
    KINDS[field],
  ]);
  const preview = createElement(
    "div",
    { className: "site-contact-form" },
    createElement(
      "fieldset",
      {
        disabled: true,
        className: "site-contact-form__fields",
        "aria-label": en
          ? "Contact form preview"
          : "Podgląd formularza kontaktowego",
      },
      ...fields.map(([label, kind]) =>
        createElement(
          "label",
          { key: label, className: "site-contact-form__field" },
          label,
          createElement(kind === "textarea" ? "textarea" : "input", {
            type: kind === "textarea" ? undefined : kind,
            readOnly: true,
            tabIndex: -1,
            rows: kind === "textarea" ? 4 : undefined,
          }),
        ),
      ),
    ),
    createElement(
      "span",
      { className: "site-section__action" },
      form.submit_label
        ? text(["submit_label"], form.submit_label)
        : en
          ? "Send message"
          : "Wyślij wiadomość",
    ),
    createElement(
      "p",
      { className: "site-contact-form__preview-note" },
      en
        ? "The form works on the published website."
        : "Formularz działa na opublikowanej stronie.",
    ),
  );
  return createElement(
    "section",
    {
      className: `site-block site-block--contact-form site-contact-form-layout--${form.layout ?? "split"}`,
      "data-block-type": "core.contact_form",
      "data-section-layout": form.layout ?? "split",
    },
    createElement(
      "div",
      { className: "site-contact-form__intro" },
      createElement(
        "h2",
        editor ? { role: "presentation" } : null,
        text(["title"], form.title),
      ),
      form.text ? createElement("p", null, text(["text"], form.text)) : null,
      form.image
        ? renderImage(
            form.image,
            createElement("img", {
              src: `/media/${form.image.asset_id}`,
              alt: form.image.alt,
              loading: "lazy",
              decoding: "async",
            }),
            imageRenderer,
          )
        : null,
    ),
    createElement(
      "div",
      { className: "site-contact-form__body" },
      formRenderer && !editor ? formRenderer(form) : preview,
      form.privacy_href
        ? createElement(
            "p",
            { className: "site-contact-form__privacy" },
            createElement(
              editor ? "span" : "a",
              {
                href: editor ? undefined : form.privacy_href,
                rel:
                  !editor && form.privacy_href.startsWith("https://")
                    ? "noreferrer"
                    : undefined,
              },
              form.privacy_label
                ? text(["privacy_label"], form.privacy_label)
                : en
                  ? "Privacy information"
                  : "Informacje o prywatności",
            ),
          )
        : null,
    ),
  );
}
