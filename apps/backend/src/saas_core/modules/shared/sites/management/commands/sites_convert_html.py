"""A dry run of the HTML → blocks converter for one file.

Reads an HTML file, prints what it becomes — how many blocks of which type,
the characters read and written, and every loss — and writes nothing: no
page, no entry, no media. An import calls `convert_html` itself; this is for
looking at one document before that.

    python manage.py sites_convert_html article.html
    python manage.py sites_convert_html article.html --json > article.json
    python manage.py sites_convert_html article.html --image https://old/a.jpg=<asset uuid>
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from ...html_blocks import convert_html, format_report


class Command(BaseCommand):
    help = (
        "Pokazuje, na jakie bloki zamieni się plik HTML i co przy tym przepada. Nic nie zapisuje."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("file", type=Path, help="Plik HTML (UTF-8).")
        parser.add_argument(
            "--json",
            action="store_true",
            help="Wypisuje bloki, straty, obrazy i liczby jako JSON zamiast raportu.",
        )
        parser.add_argument(
            "--image",
            action="append",
            default=[],
            metavar="SRC=ASSET_ID",
            help="Zasób mediów dla adresu obrazu z dokumentu; można powtarzać.",
        )
        parser.add_argument(
            "--default-image-alt",
            default="",
            help="Opis obrazu, który w dokumencie nie ma własnego.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        path: Path = options["file"]
        try:
            html = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise CommandError(f"Nie można odczytać {path}: {error}") from error
        assets: dict[str, str] = {}
        for pair in options["image"]:
            source, separator, asset = pair.rpartition("=")
            if not separator or not source or not asset:
                raise CommandError(f"--image oczekuje SRC=ASSET_ID, dostało: {pair}")
            assets[source] = asset
        conversion = convert_html(
            html, image_assets=assets, default_image_alt=options["default_image_alt"]
        )
        if options["json"]:
            self.stdout.write(
                json.dumps(
                    {
                        "blocks": conversion.blocks,
                        "losses": [asdict(loss) for loss in conversion.losses],
                        "images": list(conversion.images),
                        "stats": conversion.stats,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return
        self.stdout.write(format_report(conversion))
