"""The template-photo session end to end with the provider replaced: no call, no key."""

from __future__ import annotations

import hashlib
import json
import shutil
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from PIL import Image

from saas_core.modules.shared.image_generation.management.commands import (
    generate_template_photos as command,
)
from saas_core.modules.shared.image_generation.provider import (
    GeneratedImage,
    ImageRequest,
    ProviderError,
)

SHOT = "hoof-trimming-barn"


def jpeg(width: int, height: int) -> bytes:
    # A smooth picture compresses like a photograph; noise would not fit 400 KB.
    image = Image.linear_gradient("L").resize((width, height)).convert("RGB")
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


@pytest.fixture
def contracts(tmp_path: Path) -> Path:
    source = Path(settings.PAGE_TEMPLATE_CONTRACTS_PATH)
    target = tmp_path / "page-templates"
    (target / "assets").mkdir(parents=True)
    for name in ("photo-shots.v1.json", "sample-media.v1.json"):
        shutil.copy(source / name, target / name)
    shutil.copy(source / "assets" / "README.md", target / "assets" / "README.md")
    return target


@pytest.fixture
def requests_sent(monkeypatch: pytest.MonkeyPatch) -> list[ImageRequest]:
    sent: list[ImageRequest] = []

    def fake_generate(request: ImageRequest, *, model: str) -> GeneratedImage:
        sent.append(request)
        return GeneratedImage(
            content=jpeg(request.width, request.height),
            model=model,
            cost_usd_micros=41_000,
            provider_request_id=f"req_{len(sent)}",
            usage={"output_tokens": 1300},
        )

    monkeypatch.setattr(command, "generate", fake_generate)
    return sent


def generate_session(out: Path, contracts: Path) -> dict[str, Any]:
    call_command(
        "generate_template_photos",
        out=out,
        contracts_dir=contracts,
        only=SHOT,
        candidates=2,
    )
    return json.loads((out / "run.json").read_text(encoding="utf-8"))


def test_a_session_writes_candidates_run_record_and_contact_sheet(
    tmp_path: Path, contracts: Path, requests_sent: list[ImageRequest]
) -> None:
    out = tmp_path / "session"

    run = generate_session(out, contracts)

    assert [entry["file"] for entry in run["files"]] == [f"{SHOT}-1.jpg", f"{SHOT}-2.jpg"]
    assert run["model"] == settings.IMAGE_GENERATION_TEMPLATE_MODEL
    assert run["snapshot"] == "2026-09-08"
    assert run["files"][0]["provider_request_id"] == "req_1"
    assert run["files"][0]["cost_usd_micros"] == 41_000
    assert run["files"][0]["usage"] == {"output_tokens": 1300}
    with Image.open(out / f"{SHOT}-1.jpg") as master:
        assert master.size == (2560, 1440)
    sheet = (out / "index.html").read_text(encoding="utf-8")
    assert f'<img src="{SHOT}-2.jpg"' in sheet
    shots = json.loads((contracts / "photo-shots.v1.json").read_text(encoding="utf-8"))
    assert requests_sent[0].prompt.startswith(shots["style"])
    assert "api_key" not in json.dumps(run).lower()


def test_a_rerun_into_the_same_session_appends_and_never_pays_twice(
    tmp_path: Path, contracts: Path, requests_sent: list[ImageRequest]
) -> None:
    out = tmp_path / "session"
    generate_session(out, contracts)
    first = (out / f"{SHOT}-1.jpg").read_bytes()

    call_command(
        "generate_template_photos", out=out, contracts_dir=contracts, only=SHOT, candidates=3
    )

    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert len(requests_sent) == 3
    assert [entry["provider_request_id"] for entry in run["files"]] == ["req_1", "req_2", "req_3"]
    assert (out / f"{SHOT}-1.jpg").read_bytes() == first
    assert f'<img src="{SHOT}-1.jpg"' in (out / "index.html").read_text(encoding="utf-8")


def test_an_anchor_is_sent_as_a_reference(
    tmp_path: Path, contracts: Path, requests_sent: list[ImageRequest]
) -> None:
    shots_path = contracts / "photo-shots.v1.json"
    shots = json.loads(shots_path.read_text(encoding="utf-8"))
    shots["shots"][1]["anchors"] = [SHOT]
    shots_path.write_text(json.dumps(shots), encoding="utf-8")

    call_command(
        "generate_template_photos",
        out=tmp_path / "session",
        contracts_dir=contracts,
        only=f"{SHOT},{shots['shots'][1]['id']}",
        candidates=1,
    )

    assert requests_sent[0].references == ()
    assert requests_sent[1].references == ((tmp_path / "session" / f"{SHOT}-1.jpg").read_bytes(),)


def test_promote_writes_a_web_sized_marked_asset_and_its_catalogue_entry(
    tmp_path: Path, contracts: Path, requests_sent: list[ImageRequest]
) -> None:
    out = tmp_path / "session"
    generate_session(out, contracts)
    before = json.loads((contracts / "sample-media.v1.json").read_text(encoding="utf-8"))

    call_command("generate_template_photos", out=out, contracts_dir=contracts, promote=f"{SHOT}=2")

    content = (contracts / "assets" / f"{SHOT}.jpg").read_bytes()
    assert len(content) <= command.PROMOTED_TARGET_BYTES
    with Image.open(BytesIO(content)) as promoted:
        assert max(promoted.size) == 1920
        assert b"trainedAlgorithmicMedia" in promoted.info["xmp"]
    catalog = json.loads((contracts / "sample-media.v1.json").read_text(encoding="utf-8"))
    assert catalog["media"][: len(before["media"])] == before["media"]
    entry = catalog["media"][-1]
    assert entry["id"] == SHOT
    assert entry["contentType"] == "image/jpeg"
    assert entry["sha256"] == hashlib.sha256(content).hexdigest()
    assert entry["aiGenerated"] is True
    assert entry["alt"]["pl"] and entry["alt"]["en"]
    assert entry["provenance"].startswith(
        f"AI-generated with {settings.IMAGE_GENERATION_TEMPLATE_MODEL} on "
    )
    readme = (contracts / "assets" / "README.md").read_text(encoding="utf-8")
    assert readme.count(f"`{SHOT}.jpg`") == 1


def test_promote_refuses_to_replace_an_existing_png_that_recipes_pin(
    tmp_path: Path, contracts: Path, requests_sent: list[ImageRequest]
) -> None:
    out = tmp_path / "session"
    generate_session(out, contracts)
    shots_path = contracts / "photo-shots.v1.json"
    shots = json.loads(shots_path.read_text(encoding="utf-8"))
    shots["shots"][0]["id"] = "business"
    shots_path.write_text(json.dumps(shots), encoding="utf-8")
    (out / "business-1.jpg").write_bytes((out / f"{SHOT}-1.jpg").read_bytes())

    with pytest.raises(CommandError, match="business"):
        call_command(
            "generate_template_photos", out=out, contracts_dir=contracts, promote="business=1"
        )


def test_verify_records_a_missing_check_endpoint_as_unavailable(
    tmp_path: Path,
    contracts: Path,
    requests_sent: list[ImageRequest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "session"
    generate_session(out, contracts)
    checked: list[str] = []

    def not_found(content: bytes, *, content_type: str) -> dict[str, Any]:
        checked.append(content_type)
        raise ProviderError("openai_http_404", "invalid")

    monkeypatch.setattr(command, "check_provenance", not_found)

    call_command("generate_template_photos", verify=out)

    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["files"][0]["provenance"] == {
        "master": command.UNAVAILABLE,
        "processed": command.UNAVAILABLE,
        "preview": command.UNAVAILABLE,
    }
    # Master and processed original are JPEG, the 1280 preview is the WebP variant.
    assert checked[:3] == ["image/jpeg", "image/jpeg", "image/webp"]
