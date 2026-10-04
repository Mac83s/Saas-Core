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

/** A stay's time unit: nights, or days of a rental. */
export type StayUnit = "night" | "day";

/** What the blocks of offers booked from–to say by themselves (ADR-072,
 *  slice 5d): the list of units, the booking widget, the calendar. */
export interface StayTexts {
  /** „od 300 zł / noc”; the caller formats the amount. */
  readonly fromPrice: (amount: string, per: StayUnit | "stay") => string;
  /** „do 4 osób”. */
  readonly capacity: (count: number) => string;
  /** A unit's own action, where the block names none. */
  readonly book: string;
  /** The widget's and the calendar's action, where the block names none. */
  readonly checkDates: string;
  readonly offer: string;
  readonly choice: string;
  readonly guests: string;
  readonly arrival: (unit: StayUnit) => string;
  readonly departure: (unit: StayUnit) => string;
  /** What to pick next in the calendar. */
  readonly pick: (unit: StayUnit, step: "start" | "end") => string;
  /** „3 noce”, „2 dni”. */
  readonly length: (count: number, unit: StayUnit) => string;
  readonly previousMonth: string;
  readonly nextMonth: string;
  /** A day of the calendar, said after its date. */
  readonly free: string;
  readonly unavailable: string;
  readonly clear: string;
  readonly loading: string;
  readonly loadError: string;
  readonly noDays: string;
  readonly paused: string;
  /** In the page editor only: what the published page will show here. */
  readonly preview: {
    readonly units: string;
    readonly search: string;
    readonly calendar: string;
    readonly unit: string;
  };
  /** A picture of a unit, for whoever does not see it: „Domek 1 — zdjęcie 2”. */
  readonly photo: (name: string, number: number) => string;
}

/** One, few, many: the form a count takes in a language. */
function counted(
  locale: string,
  count: number,
  forms: { one: string; few?: string; many?: string; other: string },
): string {
  const rule = new Intl.PluralRules(locale).select(count) as keyof typeof forms;
  return `${count} ${forms[rule] ?? forms.other}`;
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
  /** Before the day an article's text last changed. */
  readonly updated: string;
  /** On a machine translation nobody has checked yet (ADR-071 pkt 17). */
  readonly machineNotice: string;
  /** Appended to an AI image's `alt`. */
  readonly aiImage: string;
  readonly pauseMotion: string;
  readonly contactForm: ContactFormTexts;
  readonly notFound: {
    readonly title: string;
    readonly body: string;
    readonly home: string;
  };
  readonly stay: StayTexts;
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
    updated: "Zaktualizowano",
    machineNotice:
      "Ten tekst przetłumaczyła maszyna i nikt go jeszcze nie sprawdził.",
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
    stay: {
      fromPrice: (amount, per) =>
        `od ${amount}${per === "night" ? " / noc" : per === "day" ? " / dzień" : ""}`,
      capacity: (count) => (count === 1 ? "do 1 osoby" : `do ${count} osób`),
      book: "Zarezerwuj",
      checkDates: "Sprawdź cenę i zarezerwuj",
      offer: "Oferta",
      choice: "Co rezerwujesz",
      guests: "Liczba osób",
      arrival: (unit) => (unit === "day" ? "Pierwszy dzień" : "Przyjazd"),
      departure: (unit) => (unit === "day" ? "Ostatni dzień" : "Wyjazd"),
      pick: (unit, step) =>
        unit === "day"
          ? step === "start"
            ? "Wybierz pierwszy dzień"
            : "Wybierz ostatni dzień"
          : step === "start"
            ? "Wybierz dzień przyjazdu"
            : "Wybierz dzień wyjazdu",
      length: (count, unit) =>
        unit === "day"
          ? counted("pl", count, { one: "dzień", other: "dni" })
          : counted("pl", count, {
              one: "noc",
              few: "noce",
              many: "nocy",
              other: "nocy",
            }),
      previousMonth: "Poprzedni miesiąc",
      nextMonth: "Następny miesiąc",
      free: "wolny termin",
      unavailable: "niedostępny",
      clear: "Wybierz inny termin",
      loading: "Sprawdzamy wolne terminy…",
      loadError:
        "Nie udało się wczytać wolnych terminów. Odśwież stronę i spróbuj ponownie.",
      noDays: "W tym miesiącu nie ma wolnych terminów.",
      paused: "Rezerwacja online jest chwilowo wstrzymana.",
      preview: {
        units:
          "Na opublikowanej stronie pojawią się tu Twoje jednostki: zdjęcie, miejscowość, wyposażenie i cena „od”. Ustawiasz je w Ustawieniach › Usługi i grafik.",
        search:
          "Na opublikowanej stronie gość wybierze tu termin i liczbę osób, a przycisk zaprowadzi go do formularza rezerwacji.",
        calendar:
          "Na opublikowanej stronie pojawi się tu kalendarz wolnych terminów z Twojego grafiku.",
        unit: "Na opublikowanej stronie pojawi się tu karta jednostki: zdjęcia, wyposażenie, cena „od” i kalendarz wolnych terminów.",
      },
      photo: (name, number) => `${name} — zdjęcie ${number}`,
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
    updated: "Updated",
    machineNotice:
      "This text was translated by a machine and nobody has checked it yet.",
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
    stay: {
      fromPrice: (amount, per) =>
        `from ${amount}${per === "night" ? " / night" : per === "day" ? " / day" : ""}`,
      capacity: (count) =>
        count === 1 ? "for 1 person" : `up to ${count} people`,
      book: "Book",
      checkDates: "Check the price and book",
      offer: "Offer",
      choice: "What you book",
      guests: "Number of people",
      arrival: (unit) => (unit === "day" ? "First day" : "Arrival"),
      departure: (unit) => (unit === "day" ? "Last day" : "Departure"),
      pick: (unit, step) =>
        unit === "day"
          ? step === "start"
            ? "Choose the first day"
            : "Choose the last day"
          : step === "start"
            ? "Choose your arrival day"
            : "Choose your departure day",
      length: (count, unit) =>
        unit === "day"
          ? counted("en", count, { one: "day", other: "days" })
          : counted("en", count, { one: "night", other: "nights" }),
      previousMonth: "Previous month",
      nextMonth: "Next month",
      free: "available",
      unavailable: "unavailable",
      clear: "Choose other dates",
      loading: "Checking available dates…",
      loadError:
        "The available dates could not be loaded. Refresh the page and try again.",
      noDays: "There are no available dates in this month.",
      paused: "Online booking is paused for now.",
      preview: {
        units:
          "The published page shows your units here: a photo, the town, the amenities and the “from” price. You set them in Settings › Services and schedule.",
        search:
          "On the published page a guest chooses the dates and the number of people here, and the button takes them to the booking form.",
        calendar:
          "The published page shows the calendar of available dates from your schedule here.",
        unit: "The published page shows the unit's card here: photos, amenities, the “from” price and the calendar of available dates.",
      },
      photo: (name, number) => `${name} — photo ${number}`,
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
    updated: "Aktualisiert",
    machineNotice:
      "Dieser Text wurde maschinell übersetzt und noch von niemandem geprüft.",
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
    stay: {
      fromPrice: (amount, per) =>
        `ab ${amount}${per === "night" ? " / Nacht" : per === "day" ? " / Tag" : ""}`,
      capacity: (count) =>
        count === 1 ? "für 1 Person" : `bis ${count} Personen`,
      book: "Buchen",
      checkDates: "Preis prüfen und buchen",
      offer: "Angebot",
      choice: "Was Sie buchen",
      guests: "Anzahl der Personen",
      arrival: (unit) => (unit === "day" ? "Erster Tag" : "Anreise"),
      departure: (unit) => (unit === "day" ? "Letzter Tag" : "Abreise"),
      pick: (unit, step) =>
        unit === "day"
          ? step === "start"
            ? "Wählen Sie den ersten Tag"
            : "Wählen Sie den letzten Tag"
          : step === "start"
            ? "Wählen Sie den Anreisetag"
            : "Wählen Sie den Abreisetag",
      length: (count, unit) =>
        unit === "day"
          ? counted("de", count, { one: "Tag", other: "Tage" })
          : counted("de", count, { one: "Nacht", other: "Nächte" }),
      previousMonth: "Vorheriger Monat",
      nextMonth: "Nächster Monat",
      free: "frei",
      unavailable: "nicht verfügbar",
      clear: "Anderen Termin wählen",
      loading: "Freie Termine werden geprüft…",
      loadError:
        "Die freien Termine konnten nicht geladen werden. Laden Sie die Seite neu und versuchen Sie es erneut.",
      noDays: "In diesem Monat gibt es keine freien Termine.",
      paused: "Die Online-Buchung ist vorübergehend ausgesetzt.",
      preview: {
        units:
          "Auf der veröffentlichten Seite erscheinen hier Ihre Einheiten: Foto, Ort, Ausstattung und der „ab“-Preis. Sie legen sie unter Einstellungen › Leistungen und Zeitplan fest.",
        search:
          "Auf der veröffentlichten Seite wählt der Gast hier Termin und Personenzahl; die Schaltfläche führt zum Buchungsformular.",
        calendar:
          "Auf der veröffentlichten Seite erscheint hier der Kalender der freien Termine aus Ihrem Zeitplan.",
        unit: "Auf der veröffentlichten Seite erscheint hier die Karte der Einheit: Fotos, Ausstattung, der „ab“-Preis und der Kalender der freien Termine.",
      },
      photo: (name, number) => `${name} — Foto ${number}`,
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
    updated: "Actualizado",
    machineNotice:
      "Este texto fue traducido por una máquina y nadie lo ha revisado todavía.",
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
    stay: {
      fromPrice: (amount, per) =>
        `desde ${amount}${per === "night" ? " / noche" : per === "day" ? " / día" : ""}`,
      capacity: (count) =>
        count === 1 ? "para 1 persona" : `hasta ${count} personas`,
      book: "Reservar",
      checkDates: "Ver el precio y reservar",
      offer: "Oferta",
      choice: "Qué reserva",
      guests: "Número de personas",
      arrival: (unit) => (unit === "day" ? "Primer día" : "Llegada"),
      departure: (unit) => (unit === "day" ? "Último día" : "Salida"),
      pick: (unit, step) =>
        unit === "day"
          ? step === "start"
            ? "Elija el primer día"
            : "Elija el último día"
          : step === "start"
            ? "Elija el día de llegada"
            : "Elija el día de salida",
      length: (count, unit) =>
        unit === "day"
          ? counted("es", count, { one: "día", other: "días" })
          : counted("es", count, { one: "noche", other: "noches" }),
      previousMonth: "Mes anterior",
      nextMonth: "Mes siguiente",
      free: "disponible",
      unavailable: "no disponible",
      clear: "Elegir otras fechas",
      loading: "Comprobando las fechas disponibles…",
      loadError:
        "No se pudieron cargar las fechas disponibles. Actualice la página e inténtelo de nuevo.",
      noDays: "No hay fechas disponibles en este mes.",
      paused: "La reserva en línea está suspendida por ahora.",
      preview: {
        units:
          "En la página publicada aparecerán aquí sus unidades: foto, localidad, equipamiento y el precio «desde». Se configuran en Ajustes › Servicios y horario.",
        search:
          "En la página publicada el huésped elegirá aquí las fechas y el número de personas, y el botón lo llevará al formulario de reserva.",
        calendar:
          "En la página publicada aparecerá aquí el calendario de fechas disponibles de su horario.",
        unit: "En la página publicada aparecerá aquí la ficha de la unidad: fotos, equipamiento, el precio «desde» y el calendario de fechas disponibles.",
      },
      photo: (name, number) => `${name} — foto ${number}`,
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
    updated: "Обновлено",
    machineNotice: "Этот текст переведён машиной, и его ещё никто не проверил.",
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
    stay: {
      fromPrice: (amount, per) =>
        `от ${amount}${per === "night" ? " / ночь" : per === "day" ? " / день" : ""}`,
      capacity: (count) =>
        count === 1 ? "для 1 человека" : `до ${count} человек`,
      book: "Забронировать",
      checkDates: "Узнать цену и забронировать",
      offer: "Предложение",
      choice: "Что вы бронируете",
      guests: "Количество человек",
      arrival: (unit) => (unit === "day" ? "Первый день" : "Заезд"),
      departure: (unit) => (unit === "day" ? "Последний день" : "Выезд"),
      pick: (unit, step) =>
        unit === "day"
          ? step === "start"
            ? "Выберите первый день"
            : "Выберите последний день"
          : step === "start"
            ? "Выберите день заезда"
            : "Выберите день выезда",
      length: (count, unit) =>
        unit === "day"
          ? counted("ru", count, {
              one: "день",
              few: "дня",
              many: "дней",
              other: "дня",
            })
          : counted("ru", count, {
              one: "ночь",
              few: "ночи",
              many: "ночей",
              other: "ночи",
            }),
      previousMonth: "Предыдущий месяц",
      nextMonth: "Следующий месяц",
      free: "свободно",
      unavailable: "недоступно",
      clear: "Выбрать другие даты",
      loading: "Проверяем свободные даты…",
      loadError:
        "Не удалось загрузить свободные даты. Обновите страницу и попробуйте ещё раз.",
      noDays: "В этом месяце нет свободных дат.",
      paused: "Онлайн-бронирование временно приостановлено.",
      preview: {
        units:
          "На опубликованной странице здесь появятся ваши объекты: фото, населённый пункт, удобства и цена «от». Они настраиваются в разделе Настройки › Услуги и расписание.",
        search:
          "На опубликованной странице гость выберет здесь даты и количество человек, а кнопка откроет форму бронирования.",
        calendar:
          "На опубликованной странице здесь появится календарь свободных дат из вашего расписания.",
        unit: "На опубликованной странице здесь появится карточка объекта: фото, удобства, цена «от» и календарь свободных дат.",
      },
      photo: (name, number) => `${name} — фото ${number}`,
    },
  },
} satisfies Record<string, SiteUiTexts>;

export type SiteUiLocale = keyof typeof TEXTS;

export const SITE_UI_LOCALES = Object.keys(TEXTS) as SiteUiLocale[];

/** The page's own language when it has texts here, else English. */
export function siteUiTexts(locale: string | undefined): SiteUiTexts {
  return (TEXTS as Record<string, SiteUiTexts>)[locale ?? "pl"] ?? TEXTS.en;
}
