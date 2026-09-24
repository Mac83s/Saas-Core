from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass
from io import BytesIO

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.PngImagePlugin import PngInfo

# IPTC DigitalSourceType for fully generated media (ADR-059 pkt 6). Written into
# the processed original and every variant of an AI asset; EXIF is still dropped.
AI_GENERATED_XMP = (
    '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF'
    ' xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about=""'
    ' xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"'
    " Iptc4xmpExt:DigitalSourceType="
    '"http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"/>'
    '</rdf:RDF></x:xmpmeta><?xpacket end="r"?>'
).encode()


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


def process_image(
    content: bytes,
    *,
    declared_mime: str,
    xmp: bytes | None = None,
) -> ProcessedImage:
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
                sanitized = _encode(normalized, detected_mime, xmp)
                variants = tuple(
                    _variant(normalized, kind=kind, size=size, xmp=xmp)
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


def _encode(image: Image.Image, content_type: str, xmp: bytes | None) -> bytes:
    output = BytesIO()
    marking: dict[str, object] = {"xmp": xmp} if xmp else {}
    if content_type == "image/jpeg":
        image.save(output, format="JPEG", quality=88, optimize=True, progressive=True, **marking)
    elif content_type == "image/png":
        # Pillow ignores `xmp=` for PNG; XMP lives in an iTXt chunk there.
        pnginfo = PngInfo()
        if xmp:
            pnginfo.add_itxt("XML:com.adobe.xmp", xmp.decode())
        image.save(output, format="PNG", optimize=True, pnginfo=pnginfo)
    else:
        image.save(output, format="WEBP", quality=85, method=6, **marking)
    return output.getvalue()


def _variant(
    image: Image.Image,
    *,
    kind: str,
    size: tuple[int, int],
    xmp: bytes | None,
) -> ProcessedVariant:
    resized = image.copy()
    resized.thumbnail(size, Image.Resampling.LANCZOS, reducing_gap=3.0)
    output = BytesIO()
    marking: dict[str, object] = {"xmp": xmp} if xmp else {}
    resized.save(output, format="WEBP", quality=82, method=6, **marking)
    return ProcessedVariant(
        kind=kind,
        content=output.getvalue(),
        content_type="image/webp",
        width=resized.width,
        height=resized.height,
    )
