from __future__ import annotations

import csv
from pathlib import Path

from pypdf import PdfReader

BASE = Path(__file__).resolve().parent
MANIFEST = BASE / "output" / "manifest.csv"
TEXT_DIR = BASE / "output" / "text"
TEXT_DIR.mkdir(parents=True, exist_ok=True)

def safe_name(relpath: str) -> str:
    # transforma input/arquivo.pdf -> input__arquivo.pdf.txt
    return relpath.replace("/", "__").replace("\\", "__") + ".txt"

def extract_text_from_pdf(pdf_path: Path, max_pages: int | None = None) -> tuple[str, int]:
    reader = PdfReader(str(pdf_path))
    pages = reader.pages
    n = len(pages)
    if max_pages is not None:
        pages = pages[:max_pages]
    out = []
    for p in pages:
        try:
            t = p.extract_text() or ""
        except Exception:
            t = ""
        if t.strip():
            out.append(t)
    return "\n".join(out), n

def main() -> None:
    if not MANIFEST.exists():
        raise SystemExit("manifest.csv não encontrado. Rode o inventory.py primeiro.")

    ok = 0
    empty = 0
    failed = 0
    skipped_ocr = 0

    with MANIFEST.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        if r["kind"] != "pdf":
            continue

        rel = r["relpath"]
        needs_ocr = r["needs_ocr"]
        in_path = BASE / Path(rel)

        if needs_ocr == "yes":
            skipped_ocr += 1
            continue

        try:
            text, n_pages = extract_text_from_pdf(in_path)
            out_path = TEXT_DIR / safe_name(rel)

            out_path.write_text(text, encoding="utf-8", errors="ignore")

            if text.strip():
                ok += 1
            else:
                empty += 1

        except Exception:
            failed += 1

    print("OK - extração concluída")
    print("Gerados em:", TEXT_DIR)
    print("PDFs processados (needs_ocr=no):", ok + empty + failed)
    print(" - com texto:", ok)
    print(" - vazio/sem texto:", empty)
    print(" - falha:", failed)
    print("PDFs pulados (needs_ocr=yes):", skipped_ocr)
    print("\nDica: abra um .txt em output\\text pra conferir se o texto veio legível.")

if __name__ == "__main__":
    main()
