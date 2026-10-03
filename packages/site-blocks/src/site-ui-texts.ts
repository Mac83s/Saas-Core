/** What a company's public site says by itself, in the language of the page
 *  (TL14): the menu's name, the language switch, pagination, the contents of
 *  an article, the AI image marking, the decoration's pause, the contact
 *  form and the missing page. Fixed interface texts, never tenant markup.
 *  A language without its own texts reads English; the platform's languages
 *  (`packages/contracts/locales/registry.json`) all have theirs. */

export interface ContactFormTexts {
  readonly name: string;
  readonly email: string;
  readonly phone: string;
  readonly message: string;
  readonly optional: string;
  readonly required: string;
  readonly invalidEmail: string;
  readonly invalidPhone: string;
  readonly tooLong: string;
  readonly submit: string;
  readonly submitting: string;
  readonly success: string;
  readonly error: string;
  readonly unavailable: string;
  readonly limited: string;
  readonly invalid: string;
  readonly conflict: string;
  readonly tooLarge: string;
}

export interface SiteUiTexts {
  readonly menu: string;
  readonly languages: string;
  readonly pagination: {
    readonly label: string;
    readonly previous: string;
    readonly next: string;
    readonly position: (current: number, total: number) => string;
  };
  readonly contents: string;
  /** Appended to an AI image's `alt`. */
  readonly aiImage: string;
  readonly pauseMotion: string;
  readonly contactForm: ContactFormTexts;
  readonly notFound: {
    readonly title: string;
    readonly body: string;
    readonly home: string;
  };
}

const TEXTS = {
  pl: {
    menu: "Menu witryny",
    languages: "Język strony",
    pagination: {
      label: "Strony",
      previous: "Poprzednia",
      next: "Następna",
      position: (current, total) => `Strona ${current} z ${total}`,
    },
    contents: "Spis treści",
    aiImage: " — obraz wygenerowany przez AI",
    pauseMotion: "Wstrzymaj animację dekoracji",
    contactForm: {
      name: "Imię i nazwisko",
      email: "Adres e-mail",
      phone: "Telefon",
      message: "Wiadomość",
      optional: "(opcjonalnie)",
      required: "Uzupełnij to pole.",
      invalidEmail: "Podaj poprawny adres e-mail.",
      invalidPhone: "Podaj poprawny numer telefonu.",
      tooLong: "Skróć treść tego pola.",
      submit: "Wyślij wiadomość",
      submitting: "Wysyłanie…",
      success: "Dziękujemy! Twoja wiadomość została przyjęta.",
      error:
        "Nie udało się potwierdzić wysłania wiadomości. Spróbuj ponownie. Twoja treść pozostała w formularzu.",
      unavailable:
        "Ten formularz nie przyjmuje obecnie wiadomości. Skorzystaj z innych danych kontaktowych na stronie.",
      limited:
        "Wysłano zbyt wiele wiadomości. Odczekaj chwilę i spróbuj ponownie.",
      invalid: "Sprawdź wprowadzone dane i spróbuj ponownie.",
      conflict:
        "Nie udało się potwierdzić wysłania wiadomości. Odśwież stronę przed kolejną próbą, zachowując wcześniej wpisaną treść.",
      tooLarge: "Wiadomość jest zbyt długa. Skróć ją i spróbuj ponownie.",
    },
    notFound: {
      title: "Nie ma takiej strony",
      body: "Adres mógł się zmienić albo strona została usunięta.",
      home: "Przejdź na stronę główną",
    },
  },
  en: {
    menu: "Menu",
    languages: "Language",
    pagination: {
      label: "Pages",
      previous: "Previous",
      next: "Next",
      position: (current, total) => `Page ${current} of ${total}`,
    },
    contents: "Contents",
    aiImage: " — AI-generated image",
    pauseMotion: "Pause decorative animation",
    contactForm: {
      name: "Full name",
      email: "Email address",
      phone: "Phone",
      message: "Message",
      optional: "(optional)",
      required: "Complete this field.",
      invalidEmail: "Enter a valid email address.",
      invalidPhone: "Enter a valid phone number.",
      tooLong: "Shorten this field.",
      submit: "Send message",
      submitting: "Sending…",
      success: "Thank you! Your message has been received.",
      error:
        "Your submission could not be confirmed. Try again. Your text is still in the form.",
      unavailable:
        "This form is not accepting messages at the moment. Please use the other contact details on this page.",
      limited:
        "Too many messages have been sent. Please wait a moment and try again.",
      invalid: "Check your details and try again.",
      conflict:
        "Your submission could not be confirmed. Save your text and refresh the page before trying again.",
      tooLarge: "Your message is too long. Shorten it and try again.",
    },
    notFound: {
      title: "Page not found",
      body: "The address may have changed, or the page was removed.",
      home: "Go to the home page",
    },
  },
  de: {
    menu: "Menü",
    languages: "Sprache",
    pagination: {
      label: "Seiten",
      previous: "Zurück",
      next: "Weiter",
      position: (current, total) => `Seite ${current} von ${total}`,
    },
    contents: "Inhalt",
    aiImage: " — KI-generiertes Bild",
    pauseMotion: "Dekorative Animation anhalten",
    contactForm: {
      name: "Vor- und Nachname",
      email: "E-Mail-Adresse",
      phone: "Telefon",
      message: "Nachricht",
      optional: "(optional)",
      required: "Bitte füllen Sie dieses Feld aus.",
      invalidEmail: "Bitte geben Sie eine gültige E-Mail-Adresse ein.",
      invalidPhone: "Bitte geben Sie eine gültige Telefonnummer ein.",
      tooLong: "Bitte kürzen Sie dieses Feld.",
      submit: "Nachricht senden",
      submitting: "Wird gesendet…",
      success: "Vielen Dank! Ihre Nachricht ist bei uns eingegangen.",
      error:
        "Das Senden konnte nicht bestätigt werden. Bitte versuchen Sie es erneut. Ihr Text bleibt im Formular.",
      unavailable:
        "Dieses Formular nimmt derzeit keine Nachrichten an. Bitte nutzen Sie die anderen Kontaktdaten auf dieser Seite.",
      limited:
        "Es wurden zu viele Nachrichten gesendet. Bitte warten Sie kurz und versuchen Sie es erneut.",
      invalid: "Bitte prüfen Sie Ihre Angaben und versuchen Sie es erneut.",
      conflict:
        "Das Senden konnte nicht bestätigt werden. Sichern Sie Ihren Text und laden Sie die Seite neu, bevor Sie es erneut versuchen.",
      tooLarge:
        "Ihre Nachricht ist zu lang. Bitte kürzen Sie sie und versuchen Sie es erneut.",
    },
    notFound: {
      title: "Seite nicht gefunden",
      body: "Die Adresse hat sich vielleicht geändert, oder die Seite wurde entfernt.",
      home: "Zur Startseite",
    },
  },
  es: {
    menu: "Menú",
    languages: "Idioma",
    pagination: {
      label: "Páginas",
      previous: "Anterior",
      next: "Siguiente",
      position: (current, total) => `Página ${current} de ${total}`,
    },
    contents: "Índice",
    aiImage: " — imagen generada por IA",
    pauseMotion: "Pausar la animación decorativa",
    contactForm: {
      name: "Nombre y apellidos",
      email: "Correo electrónico",
      phone: "Teléfono",
      message: "Mensaje",
      optional: "(opcional)",
      required: "Completa este campo.",
      invalidEmail: "Introduce un correo electrónico válido.",
      invalidPhone: "Introduce un número de teléfono válido.",
      tooLong: "Acorta este campo.",
      submit: "Enviar mensaje",
      submitting: "Enviando…",
      success: "¡Gracias! Hemos recibido tu mensaje.",
      error:
        "No se pudo confirmar el envío. Inténtalo de nuevo. Tu texto sigue en el formulario.",
      unavailable:
        "Este formulario no acepta mensajes en este momento. Utiliza los otros datos de contacto de esta página.",
      limited:
        "Se han enviado demasiados mensajes. Espera un momento e inténtalo de nuevo.",
      invalid: "Revisa tus datos e inténtalo de nuevo.",
      conflict:
        "No se pudo confirmar el envío. Guarda tu texto y recarga la página antes de volver a intentarlo.",
      tooLarge: "Tu mensaje es demasiado largo. Acórtalo e inténtalo de nuevo.",
    },
    notFound: {
      title: "Página no encontrada",
      body: "Es posible que la dirección haya cambiado o que la página se haya eliminado.",
      home: "Ir a la página de inicio",
    },
  },
  ru: {
    menu: "Меню",
    languages: "Язык",
    pagination: {
      label: "Страницы",
      previous: "Назад",
      next: "Вперёд",
      position: (current, total) => `Страница ${current} из ${total}`,
    },
    contents: "Содержание",
    aiImage: " — изображение создано ИИ",
    pauseMotion: "Остановить декоративную анимацию",
    contactForm: {
      name: "Имя и фамилия",
      email: "Адрес электронной почты",
      phone: "Телефон",
      message: "Сообщение",
      optional: "(необязательно)",
      required: "Заполните это поле.",
      invalidEmail: "Введите корректный адрес электронной почты.",
      invalidPhone: "Введите корректный номер телефона.",
      tooLong: "Сократите текст в этом поле.",
      submit: "Отправить сообщение",
      submitting: "Отправка…",
      success: "Спасибо! Ваше сообщение получено.",
      error:
        "Не удалось подтвердить отправку. Попробуйте ещё раз. Ваш текст остался в форме.",
      unavailable:
        "Эта форма сейчас не принимает сообщения. Воспользуйтесь другими контактами на этой странице.",
      limited:
        "Отправлено слишком много сообщений. Подождите немного и попробуйте снова.",
      invalid: "Проверьте введённые данные и попробуйте снова.",
      conflict:
        "Не удалось подтвердить отправку. Сохраните текст и обновите страницу, прежде чем пытаться снова.",
      tooLarge: "Сообщение слишком длинное. Сократите его и попробуйте снова.",
    },
    notFound: {
      title: "Страница не найдена",
      body: "Возможно, адрес изменился или страница была удалена.",
      home: "На главную страницу",
    },
  },
} satisfies Record<string, SiteUiTexts>;

export type SiteUiLocale = keyof typeof TEXTS;

export const SITE_UI_LOCALES = Object.keys(TEXTS) as SiteUiLocale[];

/** The page's own language when it has texts here, else English. */
export function siteUiTexts(locale: string | undefined): SiteUiTexts {
  return (TEXTS as Record<string, SiteUiTexts>)[locale ?? "pl"] ?? TEXTS.en;
}
