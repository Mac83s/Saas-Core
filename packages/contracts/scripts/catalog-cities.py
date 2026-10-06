#!/usr/bin/env python3
"""Writes packages/contracts/catalog/cities.json from two official registers.

    python3 packages/contracts/scripts/catalog-cities.py \
        PRNG_MIEJSCOWOSCI_XLSX.zip SIMC_Urzedowy_<date>.zip

- PRNG (Państwowy Rejestr Nazw Geograficznych, GUGiK), the export of localities,
  https://opendata.geoportal.gov.pl/prng/PRNG_MIEJSCOWOSCI_XLSX.zip: every object
  of the kind „miasto” with its name, voivodeship, TERYT id and main point.
- TERYT SIMC (GUS), „SIMC urzędowy” from the full files at
  https://eteryt.stat.gov.pl: the same towns by id (RM = 96). The two registers
  must agree on the set, the names and the voivodeships, or nothing is written.

A slug, once published, is an address and never changes: a town keeps the slug
the file already gives its TERYT id. A new town gets its folded name; a name
several towns share (or a slug already taken) gets the voivodeship after it.

Standard library only. Nothing here runs in the product (see catalog/README.md).
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "catalog" / "cities.json"
SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
ALPHABET = "aąbcćdeęfghijklłmnńoóprsśtuwyzźż"
# TERYT's voivodeship codes, unchanged since 1999.
VOIVODESHIPS = {
    "02": "dolnośląskie",
    "04": "kujawsko-pomorskie",
    "06": "lubelskie",
    "08": "lubuskie",
    "10": "łódzkie",
    "12": "małopolskie",
    "14": "mazowieckie",
    "16": "opolskie",
    "18": "podkarpackie",
    "20": "podlaskie",
    "22": "pomorskie",
    "24": "śląskie",
    "26": "świętokrzyskie",
    "28": "warmińsko-mazurskie",
    "30": "wielkopolskie",
    "32": "zachodniopomorskie",
}


def sheet_rows(workbook: zipfile.ZipFile):
    """The first sheet's rows as lists of text — a streamed read, the sheet is 190 MB."""
    strings = []
    with workbook.open("xl/sharedStrings.xml") as handle:
        for _event, node in ET.iterparse(handle):
            if node.tag == SHEET + "si":
                strings.append("".join(text.text or "" for text in node.iter(SHEET + "t")))
                node.clear()
    with workbook.open("xl/worksheets/sheet1.xml") as handle:
        for _event, node in ET.iterparse(handle):
            if node.tag != SHEET + "row":
                continue
            row: dict[int, str] = {}
            for cell in node.iter(SHEET + "c"):
                index = 0
                for letter in re.match(r"[A-Z]+", cell.get("r")).group(0):
                    index = index * 26 + ord(letter) - 64
                value = cell.find(SHEET + "v")
                if cell.get("t") == "inlineStr":
                    row[index - 1] = "".join(t.text or "" for t in cell.iter(SHEET + "t"))
                elif value is not None:
                    shared = cell.get("t") == "s"
                    row[index - 1] = strings[int(value.text)] if shared else value.text or ""
            yield [row.get(index, "") for index in range(max(row, default=-1) + 1)]
            node.clear()


def prng_towns(path: Path) -> tuple[str, list[dict[str, str]]]:
    """The export's date and every „miasto” of the register."""
    archive = zipfile.ZipFile(path)
    dated = [re.search(r"\d{4}-\d{2}-\d{2}", name) for name in archive.namelist()]
    exported = next(match.group(0) for match in dated if match)
    sheet = next(name for name in archive.namelist() if name.endswith("MIEJSCOWOSCI_XLSX.xlsx"))
    rows = sheet_rows(zipfile.ZipFile(io.BytesIO(archive.read(sheet))))
    header = next(rows)
    towns = []
    for row in rows:
        entry = dict(zip(header, row + [""] * (len(header) - len(row)), strict=True))
        if entry["rodzaj obiektu"] == "miasto":
            towns.append(entry)
    return exported, towns


def simc_towns(path: Path) -> tuple[str, dict[str, dict[str, str]]]:
    """The register's state date and its towns by id."""
    archive = zipfile.ZipFile(path)
    name = next(name for name in archive.namelist() if name.lower().endswith(".csv"))
    rows = list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig")), delimiter=";"))
    (state,) = {row["STAN_NA"] for row in rows}
    return state, {row["SYM"]: row for row in rows if row["RM"] == "96"}


def fold(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name.replace("ł", "l").replace("Ł", "L"))
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def degrees(text: str) -> tuple[float, float]:
    """`53°10'41" 22°03'34"` — latitude, then longitude."""
    lat, lng = (
        round(int(d) + int(m) / 60 + float(s) / 3600, 4)
        for d, m, s in re.findall(r"(\d+)°(\d+)'([\d.]+)\"", text)
    )
    return lat, lng


def polish_order(town: dict[str, object]) -> tuple[list[int], str]:
    name = str(town["name"]).lower()
    return [ALPHABET.find(char) for char in name], str(town["voivodeship"])


def main(prng_path: str, simc_path: str) -> int:
    exported, register = prng_towns(Path(prng_path))
    state, official = simc_towns(Path(simc_path))

    ids = [town["identyfikator zewnętrzny"] for town in register]
    problems = [f"PRNG only: {i}" for i in set(ids) - set(official)]
    problems += [f"SIMC only: {i} {official[i]['NAZWA']}" for i in set(official) - set(ids)]
    problems += [f"twice in PRNG: {i}" for i, count in Counter(ids).items() if count > 1]
    for town in register:
        row = official.get(town["identyfikator zewnętrzny"])
        told = (town["nazwa główna"], town["województwo"])
        if row and told != (row["NAZWA"], VOIVODESHIPS[row["WOJ"]]):
            problems.append(f"registers differ: {told} / {row['NAZWA']}, {row['WOJ']}")

    previous = json.loads(OUTPUT.read_text(encoding="utf-8"))["cities"] if OUTPUT.exists() else []
    kept = {town["teryt"]: town["slug"] for town in previous}
    problems += [f"published slug without a town: {kept[i]}" for i in set(kept) - set(ids)]
    if problems:
        print("\n".join(sorted(problems)), file=sys.stderr)
        return 1

    names = Counter(town["nazwa główna"] for town in register)
    shared = {name for name, count in names.items() if count > 1}
    taken = set(kept.values())
    cities = []
    for town in register:
        teryt, name, voivodeship = (
            town["identyfikator zewnętrzny"],
            town["nazwa główna"],
            town["województwo"],
        )
        slug = kept.get(teryt)
        if slug is None:
            slug = fold(name)
            if name in shared or slug in taken:
                slug = f"{slug}-{fold(voivodeship)}"
            if slug in taken:
                print(f"no free slug for {name}, {voivodeship}", file=sys.stderr)
                return 1
            taken.add(slug)
        lat, lng = degrees(town["współrzędne geograficzne"])
        cities.append({
            "teryt": teryt,
            "slug": slug,
            "name": name,
            "voivodeship": voivodeship,
            "lat": lat,
            "lng": lng,
        })
    cities.sort(key=polish_order)

    source = {
        "register": "Państwowy Rejestr Nazw Geograficznych (PRNG), miejscowości rodzaju „miasto”",
        "publisher": "Główny Urząd Geodezji i Kartografii",
        "url": "https://opendata.geoportal.gov.pl/prng/PRNG_MIEJSCOWOSCI_XLSX.zip",
        "exported": exported,
        "checkedAgainst": "TERYT SIMC (GUS), plik urzędowy, miejscowości RM = 96",
        "terytStateOn": state,
        "count": len(cities),
    }
    # One town a line: a year's new towns are a diff of a few lines.
    lines = ",\n".join(
        "    " + json.dumps(city, ensure_ascii=False, separators=(", ", ": ")) for city in cities
    )
    head = json.dumps({"schemaVersion": 1, "source": source}, ensure_ascii=False, indent=2)
    OUTPUT.write_text(f'{head[:-2]},\n  "cities": [\n{lines}\n  ]\n}}\n', encoding="utf-8")
    print(f"{OUTPUT}: {len(cities)} towns, PRNG {exported}, TERYT {state}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
