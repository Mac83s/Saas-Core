from __future__ import annotations

from io import BytesIO

import pytest
from django.test import override_settings
from PIL import Image

from saas_core.modules.shared.media.images import UnsafeImageError, process_image


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
