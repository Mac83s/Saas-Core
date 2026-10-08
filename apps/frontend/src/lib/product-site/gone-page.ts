/**
 * The page of an address gone for good (ADR-080): what the proxy answers 410
 * with. A whole small document, because a page of the app can say 404 but
 * not 410 — no menu and no look of the site, the address is not a page of it
 * any more. The words exist for every language of the locale registry
 * (`packages/contracts/locales/registry.json`); another one reads English.
 */
type Words = { title: string; body: string; home: string };

export const GONE_WORDS: Readonly<Record<string, Words>> = {
  pl: {
    title: "Tej strony już nie ma",
    body: "Adres, który otwierasz, został usunięty na stałe.",
    home: "Strona główna",
  },
  en: {
    title: "This page is gone",
    body: "The address you opened has been removed for good.",
    home: "Home page",
  },
  de: {
    title: "Diese Seite gibt es nicht mehr",
    body: "Die aufgerufene Adresse wurde dauerhaft entfernt.",
    home: "Startseite",
  },
  es: {
    title: "Esta página ya no existe",
    body: "La dirección que has abierto se ha eliminado de forma permanente.",
    home: "Página de inicio",
  },
  ru: {
    title: "Этой страницы больше нет",
    body: "Адрес, который вы открыли, удалён навсегда.",
    home: "Главная страница",
  },
};

/** `home`: the address of that language's home page, when the table has one. */
export function goneDocument(locale: string, home: string | null): string {
  const words = GONE_WORDS[locale] ?? GONE_WORDS.en!;
  const link = home
    ? `<p><a href="${escape(home)}">${escape(words.home)}</a></p>`
    : "";
  return `<!doctype html>
<html lang="${escape(locale)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>${escape(words.title)}</title>
<style>
body{margin:0;font-family:system-ui,sans-serif;color:#1c1917;background:#fff}
main{max-width:36rem;margin:0 auto;padding:6rem 1.5rem;text-align:center}
h1{font-size:1.5rem;font-weight:600;margin:0 0 1rem}
p{margin:0 0 1rem;color:#57534e}
a{color:#1c1917;text-decoration:underline}
</style>
</head>
<body><main><h1>${escape(words.title)}</h1><p>${escape(words.body)}</p>${link}</main></body>
</html>`;
}

function escape(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (sign) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        sign
      ] ?? sign,
  );
}
