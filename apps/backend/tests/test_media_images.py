from __future__ import annotations

from io import BytesIO

import pytest
from django.test import override_settings
from PIL import Image

from saas_core.modules.shared.media.images import (
    AI_GENERATED_XMP,
    UnsafeImageError,
    process_image,
)


def encoded_image(image_format: str, *, size: tuple[int, int] = (96, 64)) -> bytes:
    image = Image.new("RGBA", size, color=(20, 80, 160, 180))
    output = BytesIO()
    if image_format == "JPEG":
        image = image.convert("RGB")
    image.save(output, format=image_format)
    return output.getvalue()


@pytest.mark.parametrize(
    ("image_format", "content_type"),
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")],
)
def test_image_processing_accepts_allowlist_and_creates_webp_variants(
    image_format: str,
    content_type: str,
) -> None:
    processed = process_image(encoded_image(image_format), declared_mime=content_type)

    assert processed.content_type == content_type
    assert processed.width == 96
    assert processed.height == 64
    assert len(processed.sha256) == 64
    assert {variant.kind for variant in processed.variants} == {"preview", "thumbnail"}
    assert {variant.content_type for variant in processed.variants} == {"image/webp"}


@pytest.mark.parametrize(
    "payload",
    [
        b"<html><script>alert(1)</script></html>",
        b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        b"javascript:alert(1)",
        b"\xff\xd8\xfftruncated",
    ],
)
def test_image_processing_rejects_active_or_corrupted_payload(payload: bytes) -> None:
    with pytest.raises(UnsafeImageError):
        process_image(payload, declared_mime="image/jpeg")


@override_settings(MEDIA_MAX_IMAGE_PIXELS=10)
def test_image_processing_rejects_decompression_bomb() -> None:
    with pytest.raises(UnsafeImageError):
        process_image(encoded_image("PNG", size=(20, 20)), declared_mime="image/png")


MARK = b"trainedAlgorithmicMedia"


@pytest.mark.parametrize(
    ("image_format", "content_type"),
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")],
)
def test_ai_media_carries_iptc_digital_source_type_in_original_and_variants(
    image_format: str,
    content_type: str,
) -> None:
    """ADR-059 pkt 6: the machine-readable marking of Art. 50(2) in every file."""
    marked = process_image(
        encoded_image(image_format), declared_mime=content_type, xmp=AI_GENERATED_XMP
    )
    plain = process_image(encoded_image(image_format), declared_mime=content_type)

    assert MARK in marked.content
    assert all(MARK in variant.content for variant in marked.variants)
    assert len(marked.variants) == 2
    assert MARK not in plain.content
    assert not any(MARK in variant.content for variant in plain.variants)
    if image_format == "PNG":
        # Pillow ignores `xmp=` for PNG; the packet is the iTXt chunk.
        with Image.open(BytesIO(marked.content)) as decoded:
            assert MARK in decoded.text["XML:com.adobe.xmp"].encode()


def test_ai_marking_does_not_bring_exif_or_gps_back() -> None:
    image = Image.new("RGB", (64, 48), color=(10, 20, 30))
    exif = Image.Exif()
    exif[0x010E] = "private fixture metadata"
    exif.get_ifd(0x8825)[0x0002] = (52.0, 13.0, 0.0)  # GPSLatitude
    output = BytesIO()
    image.save(output, format="JPEG", exif=exif)

    processed = process_image(output.getvalue(), declared_mime="image/jpeg", xmp=AI_GENERATED_XMP)

    with Image.open(BytesIO(processed.content)) as decoded:
        assert not decoded.getexif()
    assert b"Exif" not in processed.content
    assert MARK in processed.content
