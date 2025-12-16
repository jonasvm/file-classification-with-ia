from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
IN_DIR = BASE / "input"
OUT_DIR = BASE / "output"
OUT_DIR.mkdir(exist_ok=True)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
PDF_EXTS = {".pdf"}

def sha1_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def sniff_pdf_likely_text(path: Path) -> bool:
    """
    Heurística barata (não é 100%):
    - procura sinais de texto em PDFs (ex.: /Font, BT/ET)
    - se não achar nada disso, assume "provavelmente escaneado" (OCR)
    """
    try:
        data = path.read_bytes()
    except Exception:
        return False

    # Limita pra não estourar RAM em PDF gigante
    if len(data) > 40_000_000:
        data = data[:40_000_000]

    # Sinais comuns de texto em PDFs
    markers = [b"/Font", b"BT", b"ET", b"Tf", b"Tj", b"TJ"]
    hits = sum(1 for m in markers if m in data)
    return hits >= 2

def kind_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    return "other"

def main() -> None:
    if not IN_DIR.exists():
        raise SystemExit(f"Pasta não existe: {IN_DIR}")

    rows = []
    counts = {"pdf": 0, "image": 0, "other": 0}
    ocr_yes = 0
    ocr_no = 0
    ocr_unknown = 0

    files = [p for p in IN_DIR.rglob("*") if p.is_file()]
    files.sort(key=lambda p: str(p).lower())

    for i, path in enumerate(files, start=1):
        rel = path.relative_to(BASE).as_posix()
        ext = path.suffix.lower()
        size = path.stat().st_size
        k = kind_for(path)
        counts[k] += 1

        file_sha1 = ""
        try:
            file_sha1 = sha1_file(path)
        except Exception:
            file_sha1 = "ERROR"

        # needs_ocr:
        # - imagens: sim
        # - pdf: heurística pra dizer "provavelmente texto" vs "provavelmente scan"
        # - outros: desconhecido
        needs_ocr = "unknown"
        if k == "image":
            needs_ocr = "yes"
        elif k == "pdf":
            likely_text = sniff_pdf_likely_text(path)
            needs_ocr = "no" if likely_text else "yes"

        if needs_ocr == "yes":
            ocr_yes += 1
        elif needs_ocr == "no":
            ocr_no += 1
        else:
            ocr_unknown += 1

        rows.append({
            "id": i,
            "relpath": rel,
            "ext": ext,
            "size_bytes": size,
            "sha1": file_sha1,
            "kind": k,
            "needs_ocr": needs_ocr,
        })

    out_csv = OUT_DIR / "manifest.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                          ["id","relpath","ext","size_bytes","sha1","kind","needs_ocr"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print("OK - manifest gerado:", out_csv)
    print("Total de arquivos:", len(rows))
    print("Por tipo:", counts)
    print("needs_ocr: yes =", ocr_yes, "| no =", ocr_no, "| unknown =", ocr_unknown)
    print("\nPrimeiras 5 linhas do CSV:")
    for r in rows[:5]:
        print(r["id"], r["kind"], r["needs_ocr"], r["relpath"])

if __name__ == "__main__":
    main()
