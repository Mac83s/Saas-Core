import type { ProductContent } from "./types";

/** SaaS Core Business — the generic product: a website and bookings for service businesses. */
export const business: ProductContent = {
  pl: {
    seo: {
      title: "Strona firmy i rezerwacje online dla firm usługowych",
      description:
        "Strona internetowa na własnej domenie, kalendarz rezerwacji i powiadomienia dla firm usługowych — w jednym panelu.",
    },
    hero: {
      eyebrow: "Dla firm usługowych",
      headline: "Strona firmy i rezerwacje online w jednym panelu.",
      lead: "Publikujesz stronę na własnej domenie, a klienci rezerwują wizyty w Twoim kalendarzu. Bez wtyczek, bez osobnego hostingu.",
      highlights: ["Strona firmy", "Rezerwacje", "Własna domena", "Powiadomienia"],
    },
    features: {
      title: "Obecność w sieci i umawianie klientów w jednym miejscu",
      lead: "Strona, kalendarz i powiadomienia działają razem od pierwszego dnia.",
      items: [
        { title: "Strona firmy", body: "Gotowe szablony stron — uzupełniasz treść i publikujesz." },
        { title: "Rezerwacje online", body: "Klienci widzą wolne terminy i rezerwują sami." },
        { title: "Kalendarz zespołu", body: "Usługi, grafiki, przerwy i urlopy w jednym kalendarzu." },
        { title: "Przypomnienia", body: "Automatyczne powiadomienia o wizytach dla klientów." },
        { title: "Własna domena", body: "Strona pod adresem firmy, z certyfikatem." },
        { title: "Zespół i role", body: "Każdy członek zespołu ma dostęp do tego, czego potrzebuje." },
      ],
    },
    audiences: [
      {
        title: "Dla właściciela",
        headline: "Jeden panel zamiast kilku narzędzi.",
        body: "Strona, kalendarz i rozliczenia w jednym miejscu.",
        points: ["Mniej narzędzi do opłacania", "Jedno logowanie", "Jasny abonament"],
      },
      {
        title: "Dla klientów",
        headline: "Rezerwacja w kilka kliknięć.",
        body: "Klient wybiera usługę i termin bez dzwonienia.",
        points: ["Rezerwacje całą dobę", "Przypomnienia o wizycie", "Samodzielna zmiana terminu"],
      },
    ],
    faq: [
      {
        question: "Czy potrzebuję własnego hostingu?",
        answer: "Nie. Strona, certyfikat i kalendarz działają w ramach abonamentu.",
      },
      {
        question: "Czy jest okres próbny?",
        answer: "Tak — każdy plan zaczyna się okresem próbnym.",
      },
    ],
    pricing: {
      title: "Przejrzysty abonament",
      lead: "Wybierz plan na start i zmieniaj go w panelu, kiedy chcesz.",
      note: "Ceny netto, rozliczenie miesięczne.",
      features: {
        "sites.enabled": "Strona internetowa",
        "storage.enabled": "Zdjęcia i pliki",
        "notifications.enabled": "Powiadomienia",
        "booking.enabled": "Rezerwacje online",
        "medical.enabled": "Szablony branżowe",
        "custom_domain.enabled": "Własna domena",
      },
    },
    contact: {
      title: "Porozmawiajmy",
      lead: "Napisz, czym zajmuje się Twoja firma — podpowiemy, od czego zacząć.",
      email: "kontakt@saas.goldenstar.cloud",
      area: "Polska",
    },
    footer: { tagline: "Strony i rezerwacje online dla firm usługowych." },
  },
  en: {
    seo: {
      title: "A business website and online booking for service companies",
      description:
        "A website on your own domain, a booking calendar and notifications for service businesses — in one panel.",
    },
    hero: {
      eyebrow: "For service businesses",
      headline: "Your business website and online booking in one panel.",
      lead: "Publish a site on your own domain and let customers book visits in your calendar. No plugins, no separate hosting.",
      highlights: ["Business website", "Booking", "Custom domain", "Notifications"],
    },
    features: {
      title: "Online presence and customer booking in one place",
      lead: "Website, calendar and notifications work together from day one.",
      items: [
        { title: "Business website", body: "Ready page templates — fill in the copy and publish." },
        { title: "Online booking", body: "Customers see free slots and book themselves." },
        { title: "Team calendar", body: "Services, schedules, breaks and leave in one calendar." },
        { title: "Reminders", body: "Automatic visit notifications for customers." },
        { title: "Custom domain", body: "A site at your own address, with a certificate." },
        { title: "Team and roles", body: "Everyone on the team reaches what they need." },
      ],
    },
    audiences: [
      {
        title: "For the owner",
        headline: "One panel instead of several tools.",
        body: "Website, calendar and billing in one place.",
        points: ["Fewer tools to pay for", "One sign-in", "A clear subscription"],
      },
      {
        title: "For customers",
        headline: "Booking in a few clicks.",
        body: "Customers pick a service and a time without calling.",
        points: ["Bookings around the clock", "Visit reminders", "Rescheduling on their own"],
      },
    ],
    faq: [
      {
        question: "Do I need my own hosting?",
        answer: "No. The site, certificate and calendar are part of the subscription.",
      },
      {
        question: "Is there a trial?",
        answer: "Yes — every plan starts with a trial.",
      },
    ],
    pricing: {
      title: "A clear subscription",
      lead: "Pick a plan to start and change it in the panel whenever you like.",
      note: "Prices exclude VAT, billed monthly.",
      features: {
        "sites.enabled": "Website",
        "storage.enabled": "Photos and files",
        "notifications.enabled": "Notifications",
        "booking.enabled": "Online booking",
        "medical.enabled": "Industry templates",
        "custom_domain.enabled": "Custom domain",
      },
    },
    contact: {
      title: "Let's talk",
      lead: "Tell us what your business does — we will suggest where to start.",
      email: "kontakt@saas.goldenstar.cloud",
      area: "Poland",
    },
    footer: { tagline: "Websites and online booking for service businesses." },
  },
};
