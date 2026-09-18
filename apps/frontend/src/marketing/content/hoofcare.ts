import type { ProductContent } from "./types";

/** HoofCare — copy drawn from the RACICE pre-implementation mockup. */
export const hoofcare: ProductContent = {
  pl: {
    seo: {
      title: "HoofCare — system pracy firm korekcji racic",
      description:
        "Planowanie wizyt, korekcja w terenie, historia zdrowia racic, raporty dla hodowcy i rozliczenia — w jednym systemie dla firm korekcji racic.",
    },
    hero: {
      eyebrow: "Platforma dla firm korekcji racic",
      headline: "Od wizyty w gospodarstwie do pełnej historii zdrowia racic.",
      lead: "HoofCare łączy planowanie wizyt, korekcję w terenie, historię zwierząt, raporty i rozliczenia. Bez przepisywania danych i bez dziesięciu osobnych narzędzi.",
      highlights: ["Kalendarz wizyt", "Kartoteka stada", "Raport dla hodowcy", "Zespół i role"],
    },
    features: {
      title: "Jedna aplikacja do pracy w terenie i zarządzania firmą",
      lead: "Od planu dnia po raport hodowcy — rdzeń szybki przy stanowisku, a właściciel firmy ma kontrolę nad klientami i rozliczeniami.",
      items: [
        {
          title: "Wizyty i kalendarz",
          body: "Planuj korekcje stad w kalendarzu zespołu. Każda wizyta wie, w którym gospodarstwie jest i kto ją wykonuje.",
        },
        {
          title: "Gospodarstwa i stado",
          body: "Kartoteka gospodarstw i zwierząt z numerami kolczyków — ta sama, którą korektor czyta w oborze.",
        },
        {
          title: "Korekcja w terenie",
          body: "Kończyna, strefa, diagnoza, zabieg — minimalna liczba decyzji przy krowie i duże przyciski do pracy w rękawicach.",
        },
        {
          title: "Historia zdrowia racic",
          body: "Każda korekcja, zmiana i zalecona kontrola w jednym miejscu — dla korektora i dla hodowcy.",
        },
        {
          title: "Raporty po wizycie",
          body: "Podsumowanie wizyty, zalecenia dla stada i lista zwierząt do kolejnej kontroli.",
        },
        {
          title: "Zespół i role",
          body: "Właściciel, biuro i korektorzy, każdy z dostępem dokładnie do tego, czego potrzebuje.",
        },
      ],
    },
    audiences: [
      {
        title: "Dla korektorów",
        headline: "Mniej klikania przy krowie. Więcej danych zapisanych poprawnie.",
        body: "Interfejs terenowy projektujemy na tablet, duże ekrany i pracę w rękawicach.",
        points: ["Duże przyciski i wysoki kontrast", "Szybki zapis przypadku", "Historia zwierzęcia pod ręką"],
      },
      {
        title: "Dla hodowców",
        headline: "Cała historia korekcji stada dostępna po każdej wizycie.",
        body: "Hodowca widzi wizyty, historię zwierząt, zalecenia i przypadki wymagające kolejnej kontroli.",
        points: ["Raport po każdej wizycie", "Lista krów do kontroli", "Termin kolejnej wizyty"],
      },
    ],
    faq: [
      {
        question: "Dla kogo jest HoofCare?",
        answer:
          "Dla firm i samodzielnych korektorów racic, którzy obsługują wiele gospodarstw i chcą mieć wizyty, dokumentację stad i rozliczenia w jednym miejscu.",
      },
      {
        question: "Czy mogę sprawdzić system przed zakupem?",
        answer:
          "Tak — każdy plan zaczyna się okresem próbnym. Zakładasz konto, dodajesz gospodarstwa i od razu planujesz pierwszą wizytę.",
      },
      {
        question: "Czy hodowca zobaczy dokumentację?",
        answer:
          "Hodowca dostaje wgląd w historię swojego stada i zalecenia, ale nie może zmieniać dokumentacji korektora.",
      },
      {
        question: "Czy dane moich klientów są oddzielone od innych firm?",
        answer:
          "Tak. Dane każdej firmy są izolowane na poziomie bazy danych — inna organizacja nie ma do nich dostępu.",
      },
    ],
    pricing: {
      title: "Prosty abonament dla firm korekcji racic",
      lead: "Wybierz plan na start. Zmienisz go w każdej chwili w panelu.",
      note: "Ceny netto, rozliczenie miesięczne.",
      features: {
        "sites.enabled": "Strona internetowa firmy",
        "storage.enabled": "Zdjęcia i pliki",
        "notifications.enabled": "Powiadomienia e-mail",
        "booking.enabled": "Kalendarz wizyt",
        "hoofcare.enabled": "Gospodarstwa, stado i korekcja",
        "custom_domain.enabled": "Własna domena",
      },
    },
    contact: {
      title: "Porozmawiajmy o wdrożeniu",
      lead: "Szukamy firm korekcji racic do wspólnych testów. Napisz, ile gospodarstw obsługujesz i jak dziś prowadzisz dokumentację.",
      email: "kontakt@hoofcare.goldenstar.cloud",
      area: "Polska, docelowo Europa",
    },
    footer: { tagline: "System pracy firm korekcji racic." },
  },
  en: {
    seo: {
      title: "HoofCare — the operating system for hoof trimming companies",
      description:
        "Visit planning, trimming in the field, hoof health history, farmer reports and billing — one system for hoof trimming companies.",
    },
    hero: {
      eyebrow: "The platform for hoof trimming companies",
      headline: "From a farm visit to a complete hoof health history.",
      lead: "HoofCare brings visit planning, trimming in the field, animal history, reports and billing together. No retyping, no ten separate tools.",
      highlights: ["Visit calendar", "Herd records", "Farmer report", "Team and roles"],
    },
    features: {
      title: "One app for field work and running the company",
      lead: "From the day's plan to the farmer's report — fast at the chute, with the owner in control of clients and billing.",
      items: [
        {
          title: "Visits and calendar",
          body: "Plan herd trimming in the team calendar. Every visit knows which farm it is at and who does it.",
        },
        {
          title: "Farms and herd",
          body: "Farm and animal records keyed by ear tag — the same number a trimmer reads in the barn.",
        },
        {
          title: "Trimming in the field",
          body: "Limb, zone, lesion, treatment — the fewest decisions at the cow and large targets for gloved hands.",
        },
        {
          title: "Hoof health history",
          body: "Every trim, lesion and follow-up in one place — for the trimmer and for the farmer.",
        },
        {
          title: "Visit reports",
          body: "A visit summary, herd recommendations and the list of animals due for a recheck.",
        },
        {
          title: "Team and roles",
          body: "Owner, office and trimmers, each with access to exactly what they need.",
        },
      ],
    },
    audiences: [
      {
        title: "For trimmers",
        headline: "Less tapping at the cow. More data recorded correctly.",
        body: "The field screen is designed for tablets, large targets and gloved hands.",
        points: ["Large buttons and high contrast", "Fast case entry", "Animal history at hand"],
      },
      {
        title: "For farmers",
        headline: "The herd's full trimming history after every visit.",
        body: "Farmers see visits, animal history, recommendations and cases due for a recheck.",
        points: ["A report after every visit", "Cows due for a recheck", "The next visit date"],
      },
    ],
    faq: [
      {
        question: "Who is HoofCare for?",
        answer:
          "Hoof trimming companies and independent trimmers serving many farms who want visits, herd records and billing in one place.",
      },
      {
        question: "Can I try it before buying?",
        answer:
          "Yes — every plan starts with a trial. Create an account, add farms and plan your first visit straight away.",
      },
      {
        question: "Will the farmer see the records?",
        answer:
          "Farmers see their herd's history and recommendations, but cannot change the trimmer's records.",
      },
      {
        question: "Is my clients' data separated from other companies?",
        answer:
          "Yes. Each company's data is isolated at the database level — another organization cannot reach it.",
      },
    ],
    pricing: {
      title: "A simple subscription for hoof trimming companies",
      lead: "Pick a plan to start with. You can change it any time in the panel.",
      note: "Prices exclude VAT, billed monthly.",
      features: {
        "sites.enabled": "Company website",
        "storage.enabled": "Photos and files",
        "notifications.enabled": "E-mail notifications",
        "booking.enabled": "Visit calendar",
        "hoofcare.enabled": "Farms, herd and trimming",
        "custom_domain.enabled": "Custom domain",
      },
    },
    contact: {
      title: "Let's talk about getting started",
      lead: "We are looking for hoof trimming companies to test with. Tell us how many farms you serve and how you keep records today.",
      email: "kontakt@hoofcare.goldenstar.cloud",
      area: "Poland, then Europe",
    },
    footer: { tagline: "The operating system for hoof trimming companies." },
  },
};
