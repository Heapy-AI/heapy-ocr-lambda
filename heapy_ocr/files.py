"""한정된 크기의 파일 검증과 서버 PDF 변환. 작성자: 김진우."""

from __future__ import annotations

import io
import math
import warnings
from contextlib import closing

import pypdfium2 as pdfium
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from heapy_ocr.contract import ContractError

MAX_PIXELS = 25_000_000
MAX_SIDE = 2560
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def _jpeg(image: Image.Image) -> bytes:
    if image.width * image.height > MAX_PIXELS:
        raise ContractError("IMAGE_EXPANSION_LIMIT")
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    with image.convert("RGB") as converted, io.BytesIO() as output:
        converted.save(output, format="JPEG", quality=85)
        data = output.getvalue()
    if len(data) > MAX_PAGE_BYTES:
        raise ContractError("IMAGE_EXPANSION_LIMIT")
    return data


def convert(data: bytes, extension: str, max_bytes: int) -> tuple[bytes, ...]:
    if not data or len(data) > max_bytes:
        raise ContractError("FILE_LIMIT")
    try:
        if extension == "pdf":
            return _pdf(data)
        expected = "JPEG" if extension in ("jpg", "jpeg") else "PNG"
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != expected:
                    raise ContractError("UNSUPPORTED_FORMAT")
                if image.width * image.height > MAX_PIXELS:
                    raise ContractError("IMAGE_EXPANSION_LIMIT")
                if getattr(image, "n_frames", 1) != 1:
                    raise ContractError("UNSUPPORTED_FORMAT")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                return (_jpeg(image),)
    except ContractError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ContractError("IMAGE_EXPANSION_LIMIT") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ContractError("CORRUPT_FILE") from exc


def _pdf(data: bytes) -> tuple[bytes, ...]:
    if not data.startswith(b"%PDF-"):
        raise ContractError("UNSUPPORTED_FORMAT")
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ContractError("ENCRYPTED_PDF_UNSUPPORTED")
        count = len(reader.pages)
        if not 1 <= count <= 20:
            raise ContractError("PAGE_LIMIT")
        pages = []
        total = 0
        with closing(pdfium.PdfDocument(data)) as document:
            if len(document) != count:
                raise ContractError("CORRUPT_FILE")
            for index in range(count):
                with closing(document[index]) as page:
                    width, height = page.get_size()
                    if not all(math.isfinite(x) and 0 < x <= 14400 for x in (width, height)):
                        raise ContractError("IMAGE_EXPANSION_LIMIT")
                    scale = min(150 / 72, MAX_SIDE / max(width, height))
                    with closing(page.render(scale=scale)) as bitmap, bitmap.to_pil() as image:
                        converted = _jpeg(image)
                    total += len(converted)
                    if total > MAX_TOTAL_BYTES:
                        raise ContractError("IMAGE_EXPANSION_LIMIT")
                    pages.append(converted)
        return tuple(pages)
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError("CORRUPT_FILE") from exc
