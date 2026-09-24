"""Sesja zdjęć do szablonów stron: kandydaci, weryfikacja pochodzenia, promocja (ADR-059 pkt 10).

Komenda operatora uruchamiana poza produkcją, bez bazy danych. Klucz bierze z
ustawień (`IMAGE_GENERATION_OPENAI_API_KEY_FILE`), nigdy z argumentu:

    DEPLOYMENT=business IMAGE_GENERATION_OPENAI_API_KEY_FILE=… \\
      uv run --project apps/backend python apps/backend/manage.py generate_template_photos \\
      --only hoof-trimming-barn,studio
    … generate_template_photos --verify .runtime/template-photos/2026-09-25
    … generate_template_photos --out .runtime/template-photos/2026-09-25 \\
      --promote hoof-trimming-barn=2,studio=1

Mastery (do 2560×1440) zostają w `.runtime/template-photos/`; do kontraktu
trafia JPEG o dłuższym boku ≤ 1920 px, ok. 400 KB, z `sha256` i
`aiGenerated: true`. Diff kontraktu przegląda człowiek.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from PIL import Image

from saas_core.modules.shared.media.images import AI_GENERATED_XMP, process_image

from ...provider import ImageRequest, ProviderError, check_provenance, generate

#: Master sizes per aspect: at most 2560×1440 pixels, both edges multiples of 16.
MASTER_SIZES = {
    "16:9": (2560, 1440),
    "4:3": (2048, 1536),
    "3:2": (2304, 1536),
    "1:1": (1920, 1920),
    "4:5": (1536, 1920),
}
PROMOTED_LONG_EDGE = 1920
PROMOTED_TARGET_BYTES = 400 * 1024
PROMOTED_QUALITIES = range(82, 71, -2)
UNAVAILABLE = "unavailable: verify manually at openai.com/verify"
END_USER = "saas-core:template-photos"


class Command(BaseCommand):
    help = "Generuje, weryfikuje i promuje zdjęcia do szablonów stron (bez bazy danych)."
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--out",
            type=Path,
            help="Katalog sesji; domyślnie .runtime/template-photos/<data>.",
        )
        parser.add_argument("--candidates", type=int, default=3, help="Kandydaci na ujęcie.")
        parser.add_argument("--only", default="", help="Tylko te ujęcia: id,id,…")
        parser.add_argument("--quality", choices=("high", "xhigh"), default="high")
        parser.add_argument(
            "--model",
            default="",
            help="Snapshot modelu; domyślnie IMAGE_GENERATION_TEMPLATE_MODEL.",
        )
        parser.add_argument("--verify", type=Path, help="Sprawdź pochodzenie masterów w katalogu.")
        parser.add_argument("--promote", default="", help="Promuj wybranych: id=n,id=n.")
        parser.add_argument(
            "--contracts-dir",
            type=Path,
            help="Katalog page-templates; domyślnie PAGE_TEMPLATE_CONTRACTS_PATH.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        if options["verify"]:
            self._verify(options["verify"])
            return
        contracts = Path(options["contracts_dir"] or settings.PAGE_TEMPLATE_CONTRACTS_PATH)
        shots_file = _read_json(contracts / "photo-shots.v1.json")
        out = Path(
            options["out"]
            or Path(settings.BASE_DIR).parent.parent
            / ".runtime"
            / "template-photos"
            / date.today().isoformat()
        )
        if options["promote"]:
            self._promote(out, contracts, shots_file, options["promote"])
            return
        if not 1 <= options["candidates"] <= 10:
            raise CommandError("--candidates musi być z zakresu 1-10.")
        self._generate(
            out,
            contracts,
            shots_file,
            only={item for item in options["only"].split(",") if item},
            candidates=options["candidates"],
            quality=options["quality"],
            model=options["model"] or settings.IMAGE_GENERATION_TEMPLATE_MODEL,
        )

    def _generate(
        self,
        out: Path,
        contracts: Path,
        shots_file: dict[str, Any],
        *,
        only: set[str],
        candidates: int,
        quality: str,
        model: str,
    ) -> None:
        shots = [shot for shot in shots_file["shots"] if not only or shot["id"] in only]
        if unknown := only - {shot["id"] for shot in shots}:
            raise CommandError(f"Nieznane ujęcia: {', '.join(sorted(unknown))}")
        out.mkdir(parents=True, exist_ok=True)
        run: dict[str, Any] = {
            "model": model,
            "snapshot": _snapshot(model),
            "quality": quality,
            "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
            "files": [],
        }
        try:
            self._candidates(out, contracts, shots_file, shots, run, candidates, quality, model)
        finally:
            (out / "index.html").write_text(_contact_sheet(run, shots_file), encoding="utf-8")
        total = sum(entry.get("cost_usd_micros", 0) for entry in run["files"])
        self.stdout.write(self.style.SUCCESS(f"Zapisano {out} — łącznie {total / 1e6:.3f} USD"))

    def _candidates(
        self,
        out: Path,
        contracts: Path,
        shots_file: dict[str, Any],
        shots: list[dict[str, Any]],
        run: dict[str, Any],
        candidates: int,
        quality: str,
        model: str,
    ) -> None:
        for shot in shots:
            width, height = MASTER_SIZES[shot["aspect"]]
            request = ImageRequest(
                prompt=f"{shots_file['style']}\n\n{shot['prompt']}",
                width=width,
                height=height,
                quality=quality,
                references=tuple(_anchor(out, contracts, anchor) for anchor in shot["anchors"]),
                end_user=END_USER,
            )
            for number in range(1, candidates + 1):
                name = f"{shot['id']}-{number}.jpg"
                entry: dict[str, Any] = {"shot": shot["id"], "candidate": number}
                started = time.monotonic()
                try:
                    image = generate(request, model=model)
                except ProviderError as error:
                    entry |= {"file": None, "error": error.code, "kind": error.kind}
                    run["files"].append(entry)
                    _write_run(out, run)
                    self.stderr.write(f"{name}: {error.kind} ({error.code})")
                    if error.kind in {"quota", "config"}:
                        raise CommandError(f"Przerwano: {error.code}") from error
                    continue
                (out / name).write_bytes(image.content)
                entry |= {
                    "file": name,
                    "width": width,
                    "height": height,
                    "seconds": round(time.monotonic() - started, 1),
                    "usage": dict(image.usage),
                    "cost_usd_micros": image.cost_usd_micros,
                    "provider_request_id": image.provider_request_id,
                }
                run["files"].append(entry)
                _write_run(out, run)
                self.stdout.write(f"{name}: {image.cost_usd_micros / 1e6:.3f} USD")

    def _verify(self, directory: Path) -> None:
        run = _read_json(directory / "run.json")
        for entry in run["files"]:
            if not entry.get("file"):
                continue
            master = (directory / entry["file"]).read_bytes()
            processed = process_image(master, declared_mime="image/jpeg")
            preview = next(item for item in processed.variants if item.kind == "preview")
            entry["provenance"] = {
                "master": _provenance(master, "image/jpeg"),
                "processed": _provenance(processed.content, processed.content_type),
                "preview": _provenance(preview.content, preview.content_type),
            }
            _write_run(directory, run)
            self.stdout.write(f"{entry['file']}: {json.dumps(entry['provenance'])}")

    def _promote(
        self, out: Path, contracts: Path, shots_file: dict[str, Any], selection: str
    ) -> None:
        run = _read_json(out / "run.json")
        shots = {shot["id"]: shot for shot in shots_file["shots"]}
        catalog_path = contracts / "sample-media.v1.json"
        catalog = _read_json(catalog_path)
        readme = contracts / "assets" / "README.md"
        created = str(run["createdAt"])[:10]
        for item in selection.split(","):
            shot_id, _, number = item.partition("=")
            if shot_id not in shots or not number.isdigit():
                raise CommandError(f"Nieprawidłowy wybór: {item!r} (oczekiwano id=n).")
            source = f"assets/{shot_id}.jpg"
            existing = next((m for m in catalog["media"] if m["id"] == shot_id), None)
            if existing is not None and existing["source"] != source:
                # Recipes pin the sha256 of the current file; replacing it breaks them.
                raise CommandError(f"{shot_id} to istniejące zdjęcie {existing['source']}.")
            content = _web_jpeg((out / f"{shot_id}-{number}.jpg").read_bytes())
            (contracts / source).write_bytes(content)
            entry = {
                "id": shot_id,
                "source": source,
                "filename": f"{shot_id}.jpg",
                "contentType": "image/jpeg",
                "sha256": hashlib.sha256(content).hexdigest(),
                "alt": shots[shot_id]["alt"],
                "aiGenerated": True,
                "provenance": f"AI-generated with {run['model']} on {created}",
            }
            if existing is None:
                catalog["media"].append(entry)
            else:
                catalog["media"][catalog["media"].index(existing)] = entry
            line = f"- `{shot_id}.jpg`: {shots[shot_id]['alt']['en']} — {entry['provenance']}."
            notes = [
                kept
                for kept in readme.read_text(encoding="utf-8").splitlines()
                if not kept.startswith(f"- `{shot_id}.jpg`:")
            ]
            readme.write_text("\n".join([*notes, line]) + "\n", encoding="utf-8")
            self.stdout.write(f"{source}: {len(content) // 1024} KB")
        catalog_path.write_text(
            json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CommandError(f"Nie można odczytać {path}") from error
    if not isinstance(value, dict):
        raise CommandError(f"{path} nie jest obiektem JSON")
    return value


def _write_run(directory: Path, run: dict[str, Any]) -> None:
    # Rewritten after every paid call, so a crash still leaves what was bought.
    (directory / "run.json").write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")


def _snapshot(model: str) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}$", model)
    return match.group(0) if match else ""


def _anchor(out: Path, contracts: Path, anchor: str) -> bytes:
    """The promoted photo when there is one, else this session's first candidate."""
    for path in (contracts / "assets" / f"{anchor}.jpg", out / f"{anchor}-1.jpg"):
        if path.is_file():
            return path.read_bytes()
    raise CommandError(f"Kotwica {anchor} nie ma jeszcze zdjęcia; wygeneruj ją najpierw.")


def _provenance(content: bytes, content_type: str) -> dict[str, Any] | str:
    try:
        result = check_provenance(content, content_type=content_type)
    except ProviderError as error:
        return UNAVAILABLE if error.code == "openai_http_404" else f"error: {error.code}"
    return {"c2pa": result.get("c2pa"), "synthid": result.get("synthid")}


def _web_jpeg(master: bytes) -> bytes:
    with Image.open(BytesIO(master)) as decoded:
        image = decoded.convert("RGB")
    image.thumbnail((PROMOTED_LONG_EDGE, PROMOTED_LONG_EDGE), Image.Resampling.LANCZOS)
    content = b""
    for quality in PROMOTED_QUALITIES:
        output = BytesIO()
        image.save(
            output,
            format="JPEG",
            quality=quality,
            optimize=True,
            progressive=True,
            xmp=AI_GENERATED_XMP,
        )
        content = output.getvalue()
        if len(content) <= PROMOTED_TARGET_BYTES:
            break
    return content


def _contact_sheet(run: dict[str, Any], shots_file: dict[str, Any]) -> str:
    alts = {shot["id"]: shot["alt"]["pl"] for shot in shots_file["shots"]}
    figures = "\n".join(
        f'<figure><img src="{html.escape(entry["file"])}" alt="{html.escape(alts[entry["shot"]])}"'
        f' width="480"><figcaption>{html.escape(entry["file"])}</figcaption></figure>'
        if entry.get("file")
        else f"<figure><figcaption>{html.escape(entry['shot'])}-{entry['candidate']}: "
        f"{html.escape(entry['error'])}</figcaption></figure>"
        for entry in run["files"]
    )
    return (
        '<!doctype html><html lang="pl"><meta charset="utf-8">'
        f"<title>{html.escape(run['model'])}</title>"
        "<style>body{font-family:sans-serif}figure{display:inline-block;margin:8px}</style>"
        f"<h1>{html.escape(run['model'])}</h1>\n{figures}\n</html>\n"
    )
