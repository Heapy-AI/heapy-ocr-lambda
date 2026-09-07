"""외부 API 없이 실행하는 합성 PDF 런타임 점검. 작성자: 김진우."""

import io

from pypdf import PdfWriter

from heapy_ocr.files import convert


def selftest() -> dict:
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=300, height=400)
    stream = io.BytesIO()
    writer.write(stream)
    pages = convert(stream.getvalue(), "pdf", 20_000_000)
    if len(pages) != 2 or any(not page.startswith(b"\xff\xd8") for page in pages):
        raise RuntimeError("PDF_RUNTIME_FAILED")
    return {"contractVersion": "1.0", "status": "ok", "pageCount": 2}


if __name__ == "__main__":
    print(selftest())
