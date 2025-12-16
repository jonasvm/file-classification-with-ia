from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path
from typing import Tuple, List, Dict

BASE = Path(__file__).resolve().parent
MANIFEST = BASE / "output" / "manifest.csv"
TEXT_DIR = BASE / "output" / "text"
RULES_FILE = BASE / "rules.txt"
OUT_CSV = BASE / "output" / "classified.csv"

DEFAULT_AUTO_THRESHOLD = 2  # score mínimo para AUTO
DEFAULT_REVIEW_GAP = 1      # se top1-score - top2-score <= gap => REVIEW

# ---------- Leitura robusta (encoding) ----------

def read_text_auto(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # fallback extremo (não deve chegar aqui)
    return data.decode("latin-1", errors="ignore")

# ---------- Normalização (por modo) ----------

def _clean_unicode_common(s: str) -> str:
    # Unifica formas unicode (resolve ligaduras como ﬁ, e variações)
    s = unicodedata.normalize("NFKC", s)

    # Remove “fantasmas”
    s = s.replace("\ufeff", "")  # BOM
    s = s.replace("\u00ad", "")  # soft hyphen
    s = s.replace("\u200b", "")  # zero-width space
    s = s.replace("\u200c", "")
    s = s.replace("\u200d", "")

    # NBSP -> espaço normal
    s = s.replace("\u00a0", " ")

    # Conserta hifenização comum: "micro-\nserviços" -> "microserviços"
    s = re.sub(r"-\s+", "", s)

    # Colapsa whitespace (inclui \n, \t, etc.)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _strip_accents(s: str) -> str:
    # Remove acentos mantendo letras base (João -> Joao)
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))

def normalize(s: str, *, casefold: bool, strip_accents: bool) -> str:
    s = _clean_unicode_common(s)
    if casefold:
        s = s.casefold()
    if strip_accents:
        s = _strip_accents(s)
    return s

# ---------- Regras ----------

def safe_name(relpath: str) -> str:
    return relpath.replace("/", "__").replace("\\", "__") + ".txt"

def load_rules(path: Path) -> Dict[str, List[str]]:
    """
    rules.txt:
      CATEGORIA: termo1; termo2; "frase exata"; re:...; re/i:...; ci:...; norm:...
    """
    rules: Dict[str, List[str]] = {}
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

# ---------- Matching por termo ----------
# Modos por prefixo no rules.txt:
#   lit:    literal EXATO (case+acento sensíveis)  [padrão se não tiver prefixo]
#   ci:     literal case-insensitive, acento sensível
#   na:     literal case-insensitive, SEM acento (normalize accents)
#   re:     regex case-sensitive
#   re/i:   regex IGNORECASE
#
# Observação: "frase exata" funciona em qualquer modo literal (lit/ci/na),
# e é só um literal com espaços/pontuação como digitado.

def parse_term(term: str) -> Tuple[str, str]:
    term = term.strip()
    if term.startswith("re/i:"):
        return "re_i", term[5:].strip()
    if term.startswith("re:"):
        return "re", term[3:].strip()
    if term.startswith("ci:"):
        return "ci", term[3:].strip()
    if term.startswith("na:"):
        return "na", term[3:].strip()
    if term.startswith("lit:"):
        return "lit", term[4:].strip()
    return "lit", term

def unquote_if_needed(t: str) -> str:
    t = t.strip()
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        return t[1:-1]
    return t

def count_literal(text: str, needle: str, *, casefold: bool, strip_acc: bool) -> int:
    # Normaliza ambos no mesmo modo
    tn = normalize(text, casefold=casefold, strip_accents=strip_acc)
    nn = normalize(needle, casefold=casefold, strip_accents=strip_acc)
    if not nn:
        return 0
    return tn.count(nn)

def count_regex(text: str, pattern: str, *, ignore_case: bool) -> int:
    if not pattern:
        return 0
    flags = re.MULTILINE
    if ignore_case:
        flags |= re.IGNORECASE
    try:
        return len(re.findall(pattern, text, flags=flags))
    except re.error:
        return 0

def term_match_count(text: str, term: str) -> int:
    mode, payload = parse_term(term)
    payload = unquote_if_needed(payload)

    if mode == "re":
        # regex em texto “limpo” (remove invisíveis + colapsa espaços),
        # mas mantém caixa e acento (você controla isso no pattern).
        t = _clean_unicode_common(text)
        return count_regex(t, payload, ignore_case=False)

    if mode == "re_i":
        t = _clean_unicode_common(text)
        return count_regex(t, payload, ignore_case=True)

    if mode == "ci":
        # case-insensitive, acento sensível
        return count_literal(text, payload, casefold=True, strip_acc=False)

    if mode == "na":
        # case-insensitive + sem acento (normalize accents)
        return count_literal(text, payload, casefold=True, strip_acc=True)

    # lit (padrão): literal exato (mas ainda limpa invisíveis/hifenização/whitespace)
    # Importante: aqui NÃO mudamos caixa, nem acento.
    # Ainda assim, limpamos Unicode invisível e colapsamos whitespace, pra evitar “fantasmas”.
    t = _clean_unicode_common(text)
    n = _clean_unicode_common(payload)
    if not n:
        return 0
    return t.count(n)

def best_two_categories(text: str, rules: Dict[str, List[str]]) -> Tuple[Tuple[str,int,str], Tuple[str,int,str]]:
    """
    Retorna:
      top1 = (cat, score, hits)
      top2 = (cat, score, hits)
    """
    scored: List[Tuple[str,int,str]] = []
    for cat, terms in rules.items():
        score = 0
        hits_parts = []
        for term in terms:
            c = term_match_count(text, term)
            if c > 0:
                score += c
                # não vaza conteúdo, só mostra o termo (que já está no rules)
                hits_parts.append(f"{term}({c})")
        hits = ", ".join(hits_parts)
        scored.append((cat, score, hits))

    scored.sort(key=lambda x: x[1], reverse=True)
    top1 = scored[0] if scored else ("UNKNOWN", 0, "")
    top2 = scored[1] if len(scored) > 1 else ("UNKNOWN", 0, "")
    return top1, top2

def main() -> None:
    if not MANIFEST.exists():
        raise SystemExit("manifest.csv não encontrado. Rode o inventory.py primeiro.")
    if not RULES_FILE.exists():
        raise SystemExit("rules.txt não encontrado. Crie e preencha as regras.")

    rules = load_rules(RULES_FILE)
    if not rules:
        raise SystemExit("rules.txt sem regras válidas.")

    rows = list(csv.DictReader(MANIFEST.open("r", encoding="utf-8")))
    out_rows = []

    auto = 0
    review = 0
    no_text = 0

    for r in rows:
        rel = r["relpath"]
        kind = r["kind"]

        text_path = TEXT_DIR / safe_name(rel)
        text = ""
        if text_path.exists():
            text = read_text_auto(text_path)

        if not text.strip():
            no_text += 1
            out_rows.append({
                **r,
                "label": "NO_TEXT",
                "score": "0",
                "hits": "",
                "top2_label": "",
                "top2_score": "",
                "decision": "NEEDS_OCR_OR_BETTER_EXTRACT",
            })
            continue

        (c1, s1, h1), (c2, s2, h2) = best_two_categories(text, rules)

        # decisão:
        # - precisa atingir threshold
        # - e precisa ter folga sobre o 2º (pra evitar ambiguidade)
        if s1 >= DEFAULT_AUTO_THRESHOLD and (s1 - s2) > DEFAULT_REVIEW_GAP and c1 != "UNKNOWN":
            decision = "AUTO"
            auto += 1
        else:
            decision = "REVIEW"
            review += 1

        out_rows.append({
            **r,
            "label": c1,
            "score": str(s1),
            "hits": h1,
            "top2_label": c2,
            "top2_score": str(s2),
            "decision": decision,
        })

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        fieldnames = list(out_rows[0].keys()) if out_rows else []
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    print("OK - classificação gerada:", OUT_CSV)
    print("AUTO:", auto, "| REVIEW:", review, "| NO_TEXT:", no_text)
    print("\nRegras por termo (prefixos no rules.txt):")
    print("  lit:  literal exato (case+acento sensíveis) [padrão]")
    print("  ci:   literal case-insensitive (acento sensível)")
    print("  na:   literal case-insensitive + sem acento")
    print("  re:   regex case-sensitive")
    print("  re/i: regex ignorecase")
    print("\nDica: comece com ci: para quase tudo, e use lit:/re: só quando precisar ser estrito.")

if __name__ == "__main__":
    main()
