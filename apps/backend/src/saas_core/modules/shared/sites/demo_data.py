"""The sites of the core scenario's own companies (`demo.py` reads `DEFAULTS`
by the company's key): the pages, what fills a template's „[Uzupełnij: …]”
places, and the words of every text in the company's other languages.

The other languages are written here, by hand, in the repository — no model is
called for them — and `demo.py` writes them marked as imported, not as a
person's translation and not as a machine's. A text with no entry for a
language is left untranslated, and the language is then not published.
"""

from __future__ import annotations

from typing import Any


def _block(
    kind: str, version: int, anchor: str, data: dict[str, Any], **look: Any
) -> dict[str, Any]:
    return {
        "block_type": f"core.{kind}",
        "schema_version": version,
        "data": data,
        "presentation": {"schemaVersion": 2, "inner": "standard", "anchor": anchor, **look},
    }


def _contact(title: str, text: str) -> dict[str, Any]:
    return _block(
        "contact_form",
        2,
        "kontakt",
        {
            "layout": "split",
            "contact": "email",
            "locale": "pl",
            "title": title,
            "text": text,
            "submit_label": "Wyślij pytanie",
            "success_message": "Dziękujemy! Wiadomość dotarła. Odpowiemy e-mailem.",
            "privacy_label": "Informacje o prywatności",
        },
    )


# --- Domki nad Jeziorem: the „Noclegi” template, filled in --------------------------

#: What the owner writes in place of the template's „[Uzupełnij: …]”.
_LODGING_FILL = {
    "[Uzupełnij: jedno zdanie o okolicy — jezioro, las, góry, miasteczko]": "Mikołajki to serce "
    "Mazur: jezioro za progiem, las za płotem i miasteczko z portem kwadrans spacerem.",
    "[Uzupełnij: miejsce lub atrakcja, np. plaża i pomost]": "Plaża i pomost",
    "[Uzupełnij: co tam jest i jak daleko od domków]": "Piaszczyste zejście do wody i pomost "
    "z ławkami — 40 metrów od domków.",
    "[Uzupełnij: szlak, trasa rowerowa albo kajakowa]": "Szlak kajakowy Krutyni",
    "[Uzupełnij: dla kogo i ile zajmuje]": "Spokojna rzeka także dla początkujących; "
    "jednodniowy odcinek zajmuje 4–5 godzin.",
    "[Uzupełnij: sklep, restauracja albo targ w pobliżu]": "Sklep i smażalnia ryb",
    "[Uzupełnij: jak daleko i w jakich godzinach]": "Sklep 600 metrów od domków, czynny "
    "codziennie 7:00–21:00; smażalnia w sezonie do 20:00.",
    "[Uzupełnij: co obejmuje cena, np. pościel, ręczniki, parking, drewno do kominka]": "Ręczniki, "
    "parking przy domku, drewno do kominka i Wi-Fi. Pościel możesz dobrać przy rezerwacji; "
    "sprzątanie końcowe i opłata miejscowa są doliczane do ceny.",
    "[Uzupełnij: od której godziny przyjazd i do której wyjazd]": "Przyjazd od 16:00, "
    "wyjazd do 11:00.",
    "[Uzupełnij: jak płaci się za pobyt i do kiedy można bezpłatnie odwołać rezerwację]": ""
    "Przedpłata 30% przelewem w ciągu 3 dni, reszta najpóźniej 14 dni przed przyjazdem. "
    "Rezygnacja do 30 dni przed przyjazdem — zwracamy całą przedpłatę, do 14 dni — połowę.",
    "[Uzupełnij: czy przyjmujecie zwierzęta i w jakich godzinach obowiązuje cisza]": "Psy są "
    "mile widziane za niewielką dopłatą. Cisza nocna trwa od 22:00 do 7:00.",
    "[Uzupełnij: czy macie łóżeczko, plac zabaw, zabezpieczenia].": "Tak. Mamy łóżeczko "
    "turystyczne i krzesełko do karmienia, a przy Domku Brzozowym jest plac zabaw.",
    "[Uzupełnij: gdzie i od kogo, co przy późnym przyjeździe].": "W recepcji przy wjeździe, "
    "od 16:00 do 20:00. Przy późniejszym przyjeździe zostawiamy klucz w skrytce na kod — "
    "kod wyślemy SMS-em.",
    "[Uzupełnij: Wi-Fi, zasięg sieci komórkowych].": "W każdym domku jest Wi-Fi. Zasięg sieci "
    "komórkowych jest dobry, przy samej wodzie bywa słabszy.",
    "[Uzupełnij: jak dojechać — z której drogi zjechać, gdzie zaparkować]": "Z drogi krajowej "
    "nr 16 zjedź w Mikołajkach w ulicę Leśną; po 800 metrach brama po lewej. Parkujesz przy "
    "swoim domku.",
    "Napisz — odpowiemy [Uzupełnij: w jakim czasie]. Termin najszybciej zarezerwujesz "
    "samodzielnie, w kalendarzu powyżej.": "Napisz — odpowiemy w ciągu jednego dnia roboczego. "
    "Termin najszybciej zarezerwujesz samodzielnie, w kalendarzu powyżej.",
}

#: Every text of the filled page in the company's other languages, by its
#: Polish text. English for the template's own words comes from the template's
#: English recipe; here is the rest.
_LODGING_WORDS: dict[str, dict[str, str]] = {
    "Mikołajki to serce Mazur: jezioro za progiem, las za płotem i miasteczko z portem kwadrans "
    "spacerem.": {
        "en": "Mikołajki is the heart of Masuria: the lake at your doorstep, the forest behind "
        "the fence and a harbour town a fifteen-minute walk away.",
        "de": "Mikołajki ist das Herz Masurens: der See vor der Tür, der Wald hinter dem Zaun "
        "und das Hafenstädtchen eine Viertelstunde zu Fuß entfernt.",
    },
    "Plaża i pomost": {"en": "The beach and the pier", "de": "Strand und Steg"},
    "Piaszczyste zejście do wody i pomost z ławkami — 40 metrów od domków.": {
        "en": "A sandy way into the water and a pier with benches — 40 metres from the cottages.",
        "de": "Sandiger Einstieg ins Wasser und ein Steg mit Bänken – 40 Meter von den "
        "Häusern entfernt.",
    },
    "Szlak kajakowy Krutyni": {
        "en": "The Krutynia kayak trail",
        "de": "Die Kajakroute der Krutynia",
    },
    "Spokojna rzeka także dla początkujących; jednodniowy odcinek zajmuje 4–5 godzin.": {
        "en": "A calm river, fine for beginners too; a one-day stretch takes 4–5 hours.",
        "de": "Ein ruhiger Fluss, auch für Anfänger; eine Tagesetappe dauert 4–5 Stunden.",
    },
    "Sklep i smażalnia ryb": {"en": "A shop and a fish fry", "de": "Laden und Fischbraterei"},
    "Sklep 600 metrów od domków, czynny codziennie 7:00–21:00; smażalnia w sezonie do 20:00.": {
        "en": "The shop is 600 metres from the cottages, open daily 7:00–21:00; the fish fry "
        "is open until 20:00 in season.",
        "de": "Der Laden liegt 600 Meter von den Häusern entfernt und ist täglich von 7:00 bis "
        "21:00 Uhr geöffnet; die Fischbraterei in der Saison bis 20:00 Uhr.",
    },
    "Ręczniki, parking przy domku, drewno do kominka i Wi-Fi. Pościel możesz dobrać przy "
    "rezerwacji; sprzątanie końcowe i opłata miejscowa są doliczane do ceny.": {
        "en": "Towels, parking by the cottage, firewood and Wi-Fi. Bed linen can be added when "
        "you book; the final cleaning and the local tourist tax are added to the price.",
        "de": "Handtücher, Parkplatz am Haus, Kaminholz und WLAN. Bettwäsche können Sie bei der "
        "Buchung hinzuwählen; Endreinigung und Kurtaxe kommen zum Preis hinzu.",
    },
    "Przyjazd od 16:00, wyjazd do 11:00.": {
        "en": "Arrival from 16:00, departure by 11:00.",
        "de": "Anreise ab 16:00 Uhr, Abreise bis 11:00 Uhr.",
    },
    "Przedpłata 30% przelewem w ciągu 3 dni, reszta najpóźniej 14 dni przed przyjazdem. "
    "Rezygnacja do 30 dni przed przyjazdem — zwracamy całą przedpłatę, do 14 dni — połowę.": {
        "en": "A 30% prepayment by transfer within 3 days, the rest no later than 14 days "
        "before arrival. Cancel up to 30 days before arrival and we refund the whole "
        "prepayment; up to 14 days — half.",
        "de": "30 % Anzahlung per Überweisung innerhalb von 3 Tagen, der Rest spätestens "
        "14 Tage vor der Anreise. Bei Stornierung bis 30 Tage vor der Anreise erstatten wir "
        "die gesamte Anzahlung, bis 14 Tage vorher die Hälfte.",
    },
    "Psy są mile widziane za niewielką dopłatą. Cisza nocna trwa od 22:00 do 7:00.": {
        "en": "Dogs are welcome for a small surcharge. Quiet hours are from 22:00 to 7:00.",
        "de": "Hunde sind gegen einen kleinen Aufpreis willkommen. Die Nachtruhe gilt von "
        "22:00 bis 7:00 Uhr.",
    },
    "Tak. Mamy łóżeczko turystyczne i krzesełko do karmienia, a przy Domku Brzozowym jest "
    "plac zabaw.": {
        "en": "Yes. We have a travel cot and a high chair, and there is a playground by the "
        "Birch Cottage.",
        "de": "Ja. Wir haben ein Reisebett und einen Hochstuhl, und am Birkenhaus gibt es "
        "einen Spielplatz.",
    },
    "W recepcji przy wjeździe, od 16:00 do 20:00. Przy późniejszym przyjeździe zostawiamy klucz "
    "w skrytce na kod — kod wyślemy SMS-em.": {
        "en": "At the reception by the entrance, from 16:00 to 20:00. If you arrive later, we "
        "leave the key in a code box — we will text you the code.",
        "de": "An der Rezeption an der Einfahrt, von 16:00 bis 20:00 Uhr. Bei späterer Anreise "
        "hinterlegen wir den Schlüssel im Schlüsselkasten mit Code – den Code senden wir per "
        "SMS.",
    },
    "W każdym domku jest Wi-Fi. Zasięg sieci komórkowych jest dobry, przy samej wodzie bywa "
    "słabszy.": {
        "en": "Every cottage has Wi-Fi. Mobile coverage is good; right by the water it can be "
        "weaker.",
        "de": "In jedem Haus gibt es WLAN. Der Mobilfunkempfang ist gut, direkt am Wasser kann "
        "er schwächer sein.",
    },
    "Z drogi krajowej nr 16 zjedź w Mikołajkach w ulicę Leśną; po 800 metrach brama po lewej. "
    "Parkujesz przy swoim domku.": {
        "en": "From national road 16, turn into Leśna Street in Mikołajki; after 800 metres "
        "the gate is on the left. You park by your cottage.",
        "de": "Von der Landesstraße 16 biegen Sie in Mikołajki in die Leśna-Straße ab; nach "
        "800 Metern liegt das Tor links. Sie parken an Ihrem Haus.",
    },
    "Napisz — odpowiemy w ciągu jednego dnia roboczego. Termin najszybciej zarezerwujesz "
    "samodzielnie, w kalendarzu powyżej.": {
        "en": "Write to us — we will reply within one working day. The quickest way to book is "
        "the calendar above.",
        "de": "Schreiben Sie uns – wir antworten innerhalb eines Werktags. Am schnellsten "
        "buchen Sie selbst, im Kalender oben.",
    },
    # The template's own words: English comes from its English recipe.
    "Domki nad jeziorem, w których naprawdę odpoczniesz": {
        "de": "Ferienhäuser am See, in denen Sie wirklich zur Ruhe kommen"
    },
    "Kilka domków z własnym tarasem, kilka kroków od wody i lasu. Sprawdź wolny termin "
    "i zarezerwuj pobyt online.": {
        "de": "Einige Häuser mit eigener Terrasse, nur wenige Schritte von Wasser und Wald "
        "entfernt. Prüfen Sie freie Termine und buchen Sie Ihren Aufenthalt online."
    },
    "Sprawdź wolny termin": {"de": "Freie Termine prüfen"},
    "Zobacz domki": {"de": "Häuser ansehen"},
    "Wybierz daty i liczbę osób. Cenę za cały pobyt zobaczysz w następnym kroku, zanim podasz "
    "swoje dane.": {
        "de": "Wählen Sie die Daten und die Zahl der Gäste. Den Preis für den ganzen Aufenthalt "
        "sehen Sie im nächsten Schritt, bevor Sie Ihre Daten angeben."
    },
    "Sprawdź cenę i zarezerwuj": {"de": "Preis prüfen und buchen"},
    "Wybierz miejsce dla siebie": {"de": "Wählen Sie Ihre Unterkunft"},
    "Zdjęcia, wyposażenie i cena „od” — zobacz, co Ci odpowiada, i sprawdź termin.": {
        "de": "Fotos, Ausstattung und der „ab“-Preis – sehen Sie, was zu Ihnen passt, und "
        "prüfen Sie den Termin."
    },
    "Sprawdź termin": {"de": "Termin prüfen"},
    "Co robić w okolicy": {"de": "Was man in der Umgebung unternehmen kann"},
    "Cena i zasady pobytu": {"de": "Preis und Hausordnung"},
    "Cenę za wybrany termin pokazuje formularz rezerwacji — zależy od dat i liczby osób. Tu "
    "jest to, co warto wiedzieć wcześniej.": {
        "de": "Den Preis für den gewählten Termin zeigt das Buchungsformular – er hängt von den "
        "Daten und der Zahl der Gäste ab. Hier steht, was man vorher wissen sollte."
    },
    "W cenie": {"de": "Im Preis enthalten"},
    "Przyjazd i wyjazd": {"de": "Anreise und Abreise"},
    "Płatność i odwołanie": {"de": "Zahlung und Stornierung"},
    "Zwierzęta i cisza nocna": {"de": "Haustiere und Nachtruhe"},
    "Przeczytaj regulamin rezerwacji": {"de": "Buchungsbedingungen lesen"},
    "Pytania przed przyjazdem": {"de": "Fragen vor der Anreise"},
    "Czy muszę zakładać konto, żeby zarezerwować?": {
        "de": "Muss ich ein Konto anlegen, um zu buchen?"
    },
    "Nie. Wybierasz termin i podajesz dane kontaktowe — bez zakładania konta i hasła.": {
        "de": "Nein. Sie wählen den Termin und geben Ihre Kontaktdaten an – ohne Konto und "
        "ohne Passwort."
    },
    "Czy mogę przyjechać z dziećmi?": {"de": "Kann ich mit Kindern anreisen?"},
    "Jak odebrać klucze?": {"de": "Wie bekomme ich die Schlüssel?"},
    "Czy na miejscu jest internet i zasięg?": {
        "de": "Gibt es vor Ort Internet und Mobilfunkempfang?"
    },
    "Jak do nas trafić": {"de": "So finden Sie uns"},
    "Wolne terminy": {"de": "Freie Termine"},
    "Zaznacz dzień przyjazdu i wyjazdu, a przejdziesz do rezerwacji z wybranym terminem.": {
        "de": "Markieren Sie An- und Abreisetag, und Sie gelangen mit dem gewählten Termin "
        "zur Buchung."
    },
    "Masz pytanie przed rezerwacją?": {"de": "Eine Frage vor der Buchung?"},
    "Wyślij pytanie": {"de": "Frage senden"},
    "Dziękujemy! Wiadomość dotarła. Odpowiemy e-mailem.": {
        "de": "Vielen Dank! Ihre Nachricht ist angekommen. Wir antworten per E-Mail."
    },
    "Informacje o prywatności": {"de": "Informationen zum Datenschutz"},
}

LODGING: dict[str, Any] = {
    "site": {"name": "Domki nad Jeziorem", "label": "domki-nad-jeziorem"},
    "pages": [
        {
            "key": "home",
            "name": "Noclegi",
            "type": "homepage",
            "template": "core.lodging",
            # No picture of the company's own place: the gallery asks for real
            # photos, and the demo has only the templates' illustrations.
            "drop": ["core.gallery"],
            "fill": _LODGING_FILL,
            "words": _LODGING_WORDS,
            "meta": {
                "pl": {
                    "slug": "start",
                    "title": "Domki nad Jeziorem — noclegi w Mikołajkach",
                    "description": "Domki, apartament i chata nad jeziorem w Mikołajkach. "
                    "Sprawdź wolne terminy i zarezerwuj pobyt online.",
                },
                "en": {
                    "slug": "home",
                    "title": "Domki nad Jeziorem — lakeside stays in Mikołajki",
                    "description": "Cottages, an apartment and a cabin by the lake in "
                    "Mikołajki, Masuria. Check available dates and book your stay online.",
                },
                "de": {
                    "slug": "startseite",
                    "title": "Domki nad Jeziorem — Ferienhäuser am See in Mikołajki",
                    "description": "Ferienhäuser, ein Apartment und eine Hütte am See in "
                    "Mikołajki, Masuren. Freie Termine prüfen und online buchen.",
                },
            },
        }
    ],
}


# --- Kajaki Krutynia: a page of its own with the stay blocks -------------------------

_RENTAL_WORDS: dict[str, dict[str, str]] = {
    "Kajaki na Krutyni — na dzień albo na weekend": {
        "en": "Kayaks on the Krutynia — for a day or a weekend"
    },
    "Kajaki dwuosobowe i rodzinne canoe z wiosłami i kamizelkami. Sprawdź wolne dni "
    "i zarezerwuj online — płacisz na miejscu, przy odbiorze.": {
        "en": "Two-person kayaks and a family canoe with paddles and life jackets. Check the "
        "free days and book online — you pay on site, at pickup."
    },
    "Sprawdź wolne dni": {"en": "Check free days"},
    "Wybierz sprzęt": {"en": "Choose your boat"},
    "Cena za dzień i kaucja — wszystko widzisz przed rezerwacją.": {
        "en": "The price per day and the deposit — you see it all before you book."
    },
    "Sprawdź termin": {"en": "Check dates"},
    "Wolne dni": {"en": "Free days"},
    "Zaznacz pierwszy i ostatni dzień, a przejdziesz do rezerwacji z wybranym terminem.": {
        "en": "Mark the first and the last day to continue to booking with those dates."
    },
    "Zarezerwuj": {"en": "Book"},
    "Zanim wypłyniesz": {"en": "Before you set off"},
    "O której odbiór i zwrot?": {"en": "When are pickup and return?"},
    "Kajak odbierasz od 9:00, a oddajesz do 18:00 w naszej przystani w Krutyni.": {
        "en": "You pick the kayak up from 9:00 and return it by 18:00 at our marina in Krutyń."
    },
    "Po co kaucja?": {"en": "What is the deposit for?"},
    "Kaucję pobieramy przy odbiorze i oddajemy w całości, gdy sprzęt wraca w stanie, "
    "w jakim został wydany.": {
        "en": "We take the deposit at pickup and return it in full when the equipment comes "
        "back as it was handed out."
    },
    "Co, jeśli pogoda się zepsuje?": {"en": "What if the weather turns bad?"},
    "Gdy nie da się bezpiecznie pływać, odwołujemy rezerwację sami — nic nie płacisz.": {
        "en": "When paddling is not safe, we cancel the booking ourselves — you pay nothing."
    },
    "Gdzie nas znaleźć": {"en": "Where to find us"},
    "Przystań w Krutyni, przy moście. Parking dla gości jest przy wypożyczalni.": {
        "en": "The marina in Krutyń, by the bridge. Guest parking is next to the rental."
    },
    "Masz pytanie przed rezerwacją?": {"en": "A question before you book?"},
    "Napisz — odpowiemy w ciągu jednego dnia roboczego.": {
        "en": "Write to us — we will reply within one working day."
    },
    "Wyślij pytanie": {"en": "Send your question"},
    "Dziękujemy! Wiadomość dotarła. Odpowiemy e-mailem.": {
        "en": "Thank you! Your message has arrived. We will reply by email."
    },
    "Informacje o prywatności": {"en": "Privacy information"},
}

RENTALS: dict[str, Any] = {
    "site": {"name": "Kajaki Krutynia", "label": "kajaki-krutynia"},
    "pages": [
        {
            "key": "home",
            "name": "Wypożyczalnia",
            "type": "homepage",
            "blocks": [
                {
                    "block_type": "core.hero",
                    "schema_version": 6,
                    "data": {
                        "title": "Kajaki na Krutyni — na dzień albo na weekend",
                        "text": "Kajaki dwuosobowe i rodzinne canoe z wiosłami i kamizelkami. "
                        "Sprawdź wolne dni i zarezerwuj online — płacisz na miejscu, "
                        "przy odbiorze.",
                        "action": {"label": "Sprawdź wolne dni", "href": "#terminy"},
                        "layout": "centered",
                    },
                },
                _block(
                    "stay_units",
                    1,
                    "sprzet",
                    {
                        "title": "Wybierz sprzęt",
                        "text": "Cena za dzień i kaucja — wszystko widzisz przed rezerwacją.",
                        "action_label": "Sprawdź termin",
                        "layout": "rows",
                    },
                ),
                _block(
                    "stay_calendar",
                    1,
                    "terminy",
                    {
                        "title": "Wolne dni",
                        "text": "Zaznacz pierwszy i ostatni dzień, a przejdziesz do rezerwacji "
                        "z wybranym terminem.",
                        "action_label": "Zarezerwuj",
                    },
                    surface="muted",
                ),
                _block(
                    "faq",
                    3,
                    "pytania",
                    {
                        "layout": "accordion",
                        "title": "Zanim wypłyniesz",
                        "items": [
                            {
                                "question": "O której odbiór i zwrot?",
                                "answer": "Kajak odbierasz od 9:00, a oddajesz do 18:00 "
                                "w naszej przystani w Krutyni.",
                            },
                            {
                                "question": "Po co kaucja?",
                                "answer": "Kaucję pobieramy przy odbiorze i oddajemy w całości, "
                                "gdy sprzęt wraca w stanie, w jakim został wydany.",
                            },
                            {
                                "question": "Co, jeśli pogoda się zepsuje?",
                                "answer": "Gdy nie da się bezpiecznie pływać, odwołujemy "
                                "rezerwację sami — nic nie płacisz.",
                            },
                        ],
                    },
                ),
                _block(
                    "stay_map",
                    1,
                    "dojazd",
                    {
                        "title": "Gdzie nas znaleźć",
                        "text": "Przystań w Krutyni, przy moście. Parking dla gości jest "
                        "przy wypożyczalni.",
                    },
                    surface="muted",
                ),
                _contact(
                    "Masz pytanie przed rezerwacją?",
                    "Napisz — odpowiemy w ciągu jednego dnia roboczego.",
                ),
            ],
            "words": _RENTAL_WORDS,
            "meta": {
                "pl": {
                    "slug": "start",
                    "title": "Kajaki Krutynia — wypożyczalnia kajaków",
                    "description": "Kajaki i canoe na Krutyni na dzień albo na weekend. "
                    "Sprawdź wolne dni i zarezerwuj online.",
                },
                "en": {
                    "slug": "home",
                    "title": "Kajaki Krutynia — kayak rental",
                    "description": "Kayaks and a canoe on the Krutynia for a day or a weekend. "
                    "Check the free days and book online.",
                },
            },
        }
    ],
}


# --- Studio Testowe: a plain page, only where the studio has no site yet ---------------

_STUDIO_WORDS: dict[str, dict[str, str]] = {
    "Konsultacje i warsztaty dla małych firm": {
        "en": "Consultations and workshops for small companies"
    },
    "Pomagamy uporządkować ofertę, ceny i pierwsze kroki z klientem. Spotkanie zarezerwujesz "
    "online albo telefonicznie.": {
        "en": "We help you sort out your offer, your prices and the first steps with a "
        "customer. You book a meeting online or by phone."
    },
    "Napisz do nas": {"en": "Write to us"},
    "W czym pomagamy": {"en": "What we help with"},
    "Konsultacja": {"en": "Consultation"},
    "Godzina rozmowy o jednej sprawie: ofercie, cenniku albo pierwszej kampanii.": {
        "en": "An hour about one matter: your offer, your price list or your first campaign."
    },
    "Sesja we dwoje": {"en": "Session with two consultants"},
    "Dwie osoby z naszego zespołu i jeden temat, który wymaga dwóch perspektyw.": {
        "en": "Two people from our team and one topic that needs two points of view."
    },
    "Warsztat indywidualny": {"en": "Individual workshop"},
    "Półtorej godziny pracy nad Twoim materiałem. Termin potwierdzamy po Twojej prośbie.": {
        "en": "An hour and a half of work on your own material. We confirm the time after "
        "your request."
    },
    "Pakiet startowy": {"en": "Starter package"},
    "Dwie godziny na start: plan, cennik i lista pierwszych kroków. Opłacany przelewem "
    "przed spotkaniem.": {
        "en": "Two hours to get started: a plan, a price list and a list of first steps. Paid "
        "by transfer before the meeting."
    },
    "Masz pytanie?": {"en": "A question?"},
    "Napisz — odpowiemy w ciągu jednego dnia roboczego.": {
        "en": "Write to us — we will reply within one working day."
    },
    "Wyślij pytanie": {"en": "Send your question"},
    "Dziękujemy! Wiadomość dotarła. Odpowiemy e-mailem.": {
        "en": "Thank you! Your message has arrived. We will reply by email."
    },
    "Informacje o prywatności": {"en": "Privacy information"},
}

STUDIO: dict[str, Any] = {
    "site": {"name": "Studio Testowe", "label": "studio-testowe"},
    "pages": [
        {
            "key": "home",
            "name": "Strona główna",
            "type": "homepage",
            "blocks": [
                {
                    "block_type": "core.hero",
                    "schema_version": 6,
                    "data": {
                        "title": "Konsultacje i warsztaty dla małych firm",
                        "text": "Pomagamy uporządkować ofertę, ceny i pierwsze kroki "
                        "z klientem. Spotkanie zarezerwujesz online albo telefonicznie.",
                        "action": {"label": "Napisz do nas", "href": "#kontakt"},
                        "layout": "centered",
                    },
                },
                _block(
                    "feature_list",
                    5,
                    "oferta",
                    {
                        "title": "W czym pomagamy",
                        "layout": "cards",
                        "items": [
                            {
                                "title": "Konsultacja",
                                "text": "Godzina rozmowy o jednej sprawie: ofercie, cenniku "
                                "albo pierwszej kampanii.",
                            },
                            {
                                "title": "Sesja we dwoje",
                                "text": "Dwie osoby z naszego zespołu i jeden temat, który "
                                "wymaga dwóch perspektyw.",
                            },
                            {
                                "title": "Warsztat indywidualny",
                                "text": "Półtorej godziny pracy nad Twoim materiałem. Termin "
                                "potwierdzamy po Twojej prośbie.",
                            },
                            {
                                "title": "Pakiet startowy",
                                "text": "Dwie godziny na start: plan, cennik i lista pierwszych "
                                "kroków. Opłacany przelewem przed spotkaniem.",
                            },
                        ],
                    },
                ),
                _contact("Masz pytanie?", "Napisz — odpowiemy w ciągu jednego dnia roboczego."),
            ],
            "words": _STUDIO_WORDS,
            "meta": {
                "pl": {
                    "slug": "start",
                    "title": "Studio Testowe — konsultacje i warsztaty",
                    "description": "Konsultacje i warsztaty dla małych firm: oferta, cennik "
                    "i pierwsze kroki z klientem.",
                },
                "en": {
                    "slug": "home",
                    "title": "Studio Testowe — consultations and workshops",
                    "description": "Consultations and workshops for small companies: your "
                    "offer, your price list and the first steps with a customer.",
                },
            },
        }
    ],
}

DEFAULTS: dict[str, dict[str, Any]] = {"studio": STUDIO, "domki": LODGING, "kajaki": RENTALS}
