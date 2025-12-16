from __future__ import annotations

import csv
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent
MANIFEST = BASE / "output" / "manifest.csv"
TEXT_DIR = BASE / "output" / "text"
RULES_FILE = BASE / "rules.txt"
OUT_CSV = BASE / "output" / "classified.csv"

def normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    return s

def load_rules(path: Path) -> dict[str, list[str]]:
    rules: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        cat, rest = line.split(":", 1)
        cat = cat.strip()
        terms = [t.strip() for t in rest.split(";") if t.strip()]
        rules[cat] = terms
    return rules

def term_match_count(text_norm: str, term: str) -> int:
    term = term.strip()
    if not term:
        return 0
    # frase exata se tiver aspas
    if (term.startswith('"') and term.endswith('"')) or (term.startswith("'") and term.endswith("'")):
        phrase = normalize(term[1:-1])
        return text_norm.count(phrase)
    # palavra/padrão simples (contagem por “ocorrências” aproximadas)
    t = normalize(term)
    return text_norm.count(t)

def best_category(text: str, rules: dict[str, list[str]]) -> tuple[str, int, str]:
    text_norm = normalize(text)
    best_cat = "UNKNOWN"
    best_score = 0
    best_hits = ""

    for cat, terms in rules.items():
        score = 0
        hits = []
        for term in terms:
            c = term_match_count(text_norm, term)
            if c > 0:
                score += c
                hits.append(f"{term}({c})")
        if score > best_score:
            best_score = score
            best_cat = cat
            best_hits = ", ".join(hits)

    return best_cat, best_score, best_hits

def main() -> None:
    if not MANIFEST.exists():
        raise SystemExit("manifest.csv não encontrado.")
    if not RULES_FILE.exists():
        raise SystemExit("rules.txt não encontrado. Crie e preencha as regras.")
    rules = load_rules(RULES_FILE)
    if not rules:
        raise SystemExit("rules.txt sem regras válidas.")

    rows = list(csv.DictReader(MANIFEST.open("r", encoding="utf-8")))
    out_rows = []

    auto = 0
    review = 0
    missing_text = 0

    for r in rows:
        rel = r["relpath"]
        kind = r["kind"]
        needs_ocr = r["needs_ocr"]

        text_path = TEXT_DIR / (rel.replace("/", "__").replace("\\", "__") + ".txt")
        text = ""
        if text_path.exists():
            text = text_path.read_text(encoding="utf-8", errors="ignore")

        if not text.strip():
            missing_text += 1
            out_rows.append({
                **r,
                "label": "NO_TEXT",
                "score": "0",
                "hits": "",
                "decision": "NEEDS_OCR_OR_BETTER_EXTRACT",
            })
            continue

        label, score, hits = best_category(text, rules)

        # regra simples de decisão:
        # score >= 2 => AUTO, senão REVIEW
        decision = "AUTO" if score >= 2 and label != "UNKNOWN" else "REVIEW"
        if decision == "AUTO":
            auto += 1
        else:
            review += 1

        out_rows.append({
            **r,
            "label": label,
            "score": str(score),
            "hits": hits,
            "decision": decision,
        })

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        fieldnames = list(out_rows[0].keys()) if out_rows else []
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    print("OK - classificação gerada:", OUT_CSV)
    print("AUTO:", auto, "| REVIEW:", review, "| NO_TEXT:", missing_text)
    print("\nDica: abra output\\classified.csv e veja se as categorias estão fazendo sentido.")

if __name__ == "__main__":
    main()
