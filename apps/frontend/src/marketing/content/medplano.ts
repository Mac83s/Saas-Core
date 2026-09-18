import type { ProductContent } from "./types";

/**
 * MedPlano — copy from the product brief. The pilot covers marketing, the site
 * and bookings; medical records and diagnosis are deliberately out of scope, so
 * none of it is promised here.
 */
export const medplano: ProductContent = {
  pl: {
    seo: {
      title: "MedPlano — strona i rezerwacje online dla gabinetów i klinik",
      description:
        "Własna strona gabinetu na Twojej domenie i rezerwacje wizyt online — bez prowizji od pacjenta i bez budowania marki na cudzej platformie.",
    },
    hero: {
      eyebrow: "Dla lekarzy, gabinetów i klinik",
      headline: "Własna strona gabinetu i rezerwacje online. Bez opłaty za pacjenta.",
      lead: "MedPlano daje gabinetowi stronę na własnej domenie i kalendarz, w którym pacjenci sami rezerwują wizyty. Budujesz swoją markę, a nie profil na cudzej platformie.",
      highlights: ["Strona gabinetu", "Rezerwacje online", "Własna domena", "Bez prowizji"],
    },
    features: {
      title: "Wszystko, czego gabinet potrzebuje w sieci",
      lead: "Strona, kalendarz i powiadomienia działają razem — pacjent trafia na stronę i od razu rezerwuje termin.",
      items: [
        {
          title: "Strona gabinetu",
          body: "Gotowe szablony dla gabinetu i specjalisty. Uzupełniasz treść, publikujesz jednym kliknięciem.",
        },
        {
          title: "Rezerwacje online",
          body: "Pacjent widzi wolne terminy i rezerwuje wizytę sam, o każdej porze.",
        },
        {
          title: "Kalendarz i grafik",
          body: "Usługi, czas trwania wizyt, przerwy i urlopy — jeden kalendarz dla całego gabinetu.",
        },
        {
          title: "Przypomnienia",
          body: "Automatyczne przypomnienia o wizycie ograniczają nieobecności.",
        },
        {
          title: "Własna domena",
          body: "Strona pod adresem gabinetu, z certyfikatem i bez reklam platformy.",
        },
        {
          title: "Minimum danych wrażliwych",
          body: "Zbieramy tylko to, co potrzebne do rezerwacji — bez dokumentacji medycznej.",
        },
      ],
    },
    audiences: [
      {
        title: "Dla gabinetu",
        headline: "Pacjenci rezerwują sami, recepcja ma mniej telefonów.",
        body: "Kalendarz online przejmuje umawianie wizyt, a przypomnienia pilnują frekwencji.",
        points: ["Rezerwacje całą dobę", "Mniej nieobecności", "Jeden kalendarz dla zespołu"],
      },
      {
        title: "Dla lekarza",
        headline: "Twoja marka i Twoja pozycja w wyszukiwarce.",
        body: "Strona na własnej domenie buduje rozpoznawalność gabinetu, a nie platformy pośrednika.",
        points: ["Własna domena", "Strona zoptymalizowana pod SEO", "Bez prowizji od pacjenta"],
      },
    ],
    faq: [
      {
        question: "Czym MedPlano różni się od serwisów z rezerwacjami?",
        answer:
          "Nie pobieramy opłaty za pacjenta i nie budujesz profilu na cudzej platformie. Strona i domena są Twoje.",
      },
      {
        question: "Czy mogę przenieść obecną stronę?",
        answer:
          "Tak. Pomagamy przenieść treść i adres strony, z możliwością cofnięcia zmiany, gdyby coś poszło nie tak.",
      },
      {
        question: "Czy przechowujecie dokumentację medyczną?",
        answer:
          "Nie. MedPlano obsługuje stronę i rezerwacje — dane zbieramy wyłącznie w zakresie potrzebnym do umówienia wizyty.",
      },
      {
        question: "Czy jest okres próbny?",
        answer: "Tak — każdy plan zaczyna się okresem próbnym po aktywacji pierwszej strony.",
      },
    ],
    pricing: {
      title: "Przejrzysty abonament, bez opłat za pacjenta",
      lead: "Płacisz stałą kwotę miesięcznie, niezależnie od liczby pacjentów.",
      note: "Ceny netto, rozliczenie miesięczne. Własna domena w planie Pro.",
      features: {
        "sites.enabled": "Strona gabinetu",
        "storage.enabled": "Zdjęcia i pliki",
        "notifications.enabled": "Powiadomienia i przypomnienia",
        "booking.enabled": "Rezerwacje online",
        "medical.enabled": "Szablony dla gabinetów",
        "custom_domain.enabled": "Własna domena",
      },
    },
    contact: {
      title: "Porozmawiajmy o Twoim gabinecie",
      lead: "Napisz, ilu specjalistów przyjmuje w gabinecie i jak dziś umawiasz wizyty — pokażemy, jak to wygląda w MedPlano.",
      email: "kontakt@medplano.goldenstar.cloud",
      area: "Polska",
    },
    footer: { tagline: "Strony i rezerwacje online dla gabinetów i klinik." },
  },
  en: {
    seo: {
      title: "MedPlano — a website and online booking for practices and clinics",
      description:
        "Your practice's own website on your own domain and online booking — no per-patient fee and no brand built on someone else's platform.",
    },
    hero: {
      eyebrow: "For doctors, practices and clinics",
      headline: "Your practice's own website and online booking. No per-patient fee.",
      lead: "MedPlano gives a practice a website on its own domain and a calendar where patients book visits themselves. You build your brand, not a profile on someone else's platform.",
      highlights: ["Practice website", "Online booking", "Custom domain", "No commission"],
    },
    features: {
      title: "Everything a practice needs online",
      lead: "Website, calendar and notifications work together — a patient lands on the site and books straight away.",
      items: [
        {
          title: "Practice website",
          body: "Ready templates for a practice and a specialist. Fill in the copy and publish in one click.",
        },
        {
          title: "Online booking",
          body: "Patients see free slots and book a visit themselves, at any hour.",
        },
        {
          title: "Calendar and schedule",
          body: "Services, visit lengths, breaks and leave — one calendar for the whole practice.",
        },
        {
          title: "Reminders",
          body: "Automatic visit reminders cut down no-shows.",
        },
        {
          title: "Custom domain",
          body: "A site at the practice's own address, with a certificate and no platform ads.",
        },
        {
          title: "Minimal sensitive data",
          body: "We collect only what a booking needs — no medical records.",
        },
      ],
    },
    audiences: [
      {
        title: "For the practice",
        headline: "Patients book themselves, reception takes fewer calls.",
        body: "The online calendar handles scheduling and reminders keep attendance up.",
        points: ["Bookings around the clock", "Fewer no-shows", "One calendar for the team"],
      },
      {
        title: "For the doctor",
        headline: "Your brand and your position in search.",
        body: "A website on your own domain builds the practice's recognition, not an intermediary's.",
        points: ["Custom domain", "SEO-ready website", "No per-patient fee"],
      },
    ],
    faq: [
      {
        question: "How is MedPlano different from booking marketplaces?",
        answer:
          "We charge no per-patient fee and you do not build a profile on someone else's platform. The site and domain are yours.",
      },
      {
        question: "Can I move my current website?",
        answer:
          "Yes. We help move the content and address, with a way to roll back if something goes wrong.",
      },
      {
        question: "Do you store medical records?",
        answer:
          "No. MedPlano handles the website and bookings — we collect only what is needed to book a visit.",
      },
      {
        question: "Is there a trial?",
        answer: "Yes — every plan starts with a trial once your first site is activated.",
      },
    ],
    pricing: {
      title: "A clear subscription, no per-patient fees",
      lead: "One fixed monthly price, however many patients you see.",
      note: "Prices exclude VAT, billed monthly. Custom domain on the Pro plan.",
      features: {
        "sites.enabled": "Practice website",
        "storage.enabled": "Photos and files",
        "notifications.enabled": "Notifications and reminders",
        "booking.enabled": "Online booking",
        "medical.enabled": "Templates for practices",
        "custom_domain.enabled": "Custom domain",
      },
    },
    contact: {
      title: "Let's talk about your practice",
      lead: "Tell us how many specialists see patients and how you book visits today — we will show you how it works in MedPlano.",
      email: "kontakt@medplano.goldenstar.cloud",
      area: "Poland",
    },
    footer: { tagline: "Websites and online booking for practices and clinics." },
  },
};
