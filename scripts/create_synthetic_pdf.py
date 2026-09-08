"""실제 개인정보가 없는 OCR 연결 점검용 PDF 생성. 작성자: 김진우."""

from pathlib import Path


def synthetic_pdf():
    lines = [
        "GENERAL HEALTH CHECKUP - SYNTHETIC TEST ONLY",
        "Examination date: 2026-09-08",
        "Provider: Synthetic Test Clinic",
        "Height: 170 cm",
        "Weight: 65 kg",
        "Fasting blood glucose: 95 mg/dL",
        "Hemoglobin: 14 g/dL",
    ]
    stream = (
        "BT /F1 14 Tf 45 780 Td 28 TL " + " T* ".join("(" + line + ") Tj" for line in lines) + " ET"
    ).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    data = b"%PDF-1.4\n"
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    start = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    data += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    return data


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="비식별 합성 OCR 테스트 PDF 생성")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.output.open("xb") as target:
        target.write(synthetic_pdf())
    print("합성 PDF 생성 완료:", args.output)
