import { createElement } from "react";
import { plainBlockText } from "./block-text";
import type { BlockComponentProps, ContactFormV1Data } from "./types";

/** The catalogue/editor show a disabled fieldset; only a publication supplies
 * the application form adapter with its immutable publication and position. */
export function ContactFormSection({
  data,
  editor,
  imageRenderer,
  formRenderer,
}: BlockComponentProps) {
  const form = data as ContactFormV1Data;
  const text = editor?.text ?? plainBlockText;
  const en = form.locale === "en";
  const fields = en
    ? [
        ["Name", "text"],
        ["Email", "email"],
        ["Phone (optional)", "tel"],
        ["Message", "textarea"],
      ]
    : [
        ["Imię", "text"],
        ["E-mail", "email"],
        ["Telefon (opcjonalnie)", "tel"],
        ["Wiadomość", "textarea"],
      ];
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
        ? imageRenderer
          ? imageRenderer(form.image)
          : createElement("img", {
              src: `/media/${form.image.asset_id}`,
              alt: form.image.alt,
              loading: "lazy",
              decoding: "async",
            })
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
