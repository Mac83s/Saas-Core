from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from io import BytesIO

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError


class UnsafeImageError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProcessedVariant:
    kind: str
    content: bytes
    content_type: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class ProcessedImage:
    content: bytes
    content_type: str
    sha256: str
    width: int
    height: int
    variants: tuple[ProcessedVariant, ...]


FORMAT_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
VARIANT_SIZES = {
    "thumbnail": (320, 320),
    "preview": (1280, 1280),
}


def process_image(content: bytes, *, declared_mime: str) -> ProcessedImage:
    detected_mime = detect_image_mime(content)
    if detected_mime != declared_mime:
        raise UnsafeImageError("Rzeczywisty typ obrazu nie zgadza się z deklaracją.")

    Image.MAX_IMAGE_PIXELS = settings.MEDIA_MAX_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as probe:
                if FORMAT_MIME.get(probe.format or "") != detected_mime:
                    raise UnsafeImageError("Dekoder obrazu nie potwierdził typu pliku.")
                if getattr(probe, "n_frames", 1) != 1:
                    raise UnsafeImageError("Animowane obrazy nie są obsługiwane.")
                probe.verify()
            with Image.open(BytesIO(content)) as decoded:
                decoded.load()
                image = ImageOps.exif_transpose(decoded)
                image.load()
                width, height = image.size
                if width <= 0 or height <= 0:
                    raise UnsafeImageError("Obraz ma nieprawidłowe wymiary.")
                normalized = _normalized_mode(image, detected_mime)
                sanitized = _encode(normalized, detected_mime)
                variants = tuple(
                    _variant(normalized, kind=kind, size=size)
                    for kind, size in VARIANT_SIZES.items()
                )
    except UnsafeImageError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        ValueError,
    ) as error:
        raise UnsafeImageError("Obraz jest uszkodzony albo niebezpieczny.") from error

    return ProcessedImage(
        content=sanitized,
        content_type=detected_mime,
        sha256=hashlib.sha256(sanitized).hexdigest(),
        width=width,
        height=height,
        variants=variants,
    )


def detect_image_mime(content: bytes) -> str:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    raise UnsafeImageError("Plik nie ma dozwolonych magic bytes obrazu.")


def _normalized_mode(image: Image.Image, content_type: str) -> Image.Image:
    if content_type == "image/jpeg":
        return image.convert("RGB")
    if "A" in image.getbands():
        return image.convert("RGBA")
    return image.convert("RGB")


def _encode(image: Image.Image, content_type: str) -> bytes:
    output = BytesIO()
    if content_type == "image/jpeg":
        image.save(output, format="JPEG", quality=88, optimize=True, progressive=True)
    elif content_type == "image/png":
        image.save(output, format="PNG", optimize=True)
    else:
        image.save(output, format="WEBP", quality=85, method=6)
    return output.getvalue()


def _variant(
    image: Image.Image,
    *,
    kind: str,
    size: tuple[int, int],
) -> ProcessedVariant:
    resized = image.copy()
    resized.thumbnail(size, Image.Resampling.LANCZOS, reducing_gap=3.0)
    output = BytesIO()
    resized.save(output, format="WEBP", quality=82, method=6)
    return ProcessedVariant(
        kind=kind,
        content=output.getvalue(),
        content_type="image/webp",
        width=resized.width,
        height=resized.height,
    )
