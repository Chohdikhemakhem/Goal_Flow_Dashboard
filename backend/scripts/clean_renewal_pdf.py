from __future__ import annotations

import re
from pathlib import Path
import unicodedata

import pandas as pd
import pdfplumber

INPUT_PDF = Path("/mnt/user-data/uploads/microcred_renewal_candidates.pdf")
OUTPUT_CSV = Path("/mnt/user-data/outputs/microcred_renewal_clean.csv")

COLUMNS = [
    "CLIENT_NO",
    "CLIENT_NAME",
    "CLIENT_FIRST_NAME",
    "CATEGORY_DESC",
    "DISBURSEMENT_AMOUNT",
    "MATURITY_DATE",
    "ENCOURS",
]

WHITESPACE_RE = re.compile(r"\s+")
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
BIDI_MARKS_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")
AR_TOKEN_RE = re.compile(r"^[\u0600-\u06FF]+$")
NON_CONNECTORS = set("اأإآدذرزوؤ")
COMMON_AR_PREFIXES = ("ال", "لل", "بال", "وال", "فال", "كال")
COMMON_AR_SUFFIXES = ("ة", "ات", "ية", "ي", "ين", "ون", "ان")


def normalize_cell(value: str | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    text = BIDI_MARKS_RE.sub("", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def _arabic_orientation_score(text: str) -> float:
    score = 0.0
    words = [w for w in text.split() if AR_TOKEN_RE.match(w)]
    if not words:
        return score

    for word in words:
        if word.startswith(COMMON_AR_PREFIXES):
            score += 2.0
        if word.endswith(COMMON_AR_SUFFIXES):
            score += 1.0
        if word.startswith(("ة", "ى", "ئ")):
            score -= 1.5
        if word.endswith(("ل", "ب", "ك")):
            score -= 0.5

        # Connectivity heuristic: reversed words often create odd non-connector patterns.
        for left, right in zip(word, word[1:]):
            if left in NON_CONNECTORS and AR_TOKEN_RE.match(right):
                score -= 0.15

    return score


def _reverse_arabic_candidates(text: str) -> list[str]:
    tokens = text.split()
    if not tokens:
        return [text]

    c0 = text
    c1 = " ".join(tok[::-1] for tok in reversed(tokens))  # full visual->logical repair
    c2 = " ".join(tok[::-1] for tok in tokens)            # reverse letters only
    c3 = " ".join(reversed(tokens))                       # reverse words only
    return [c0, c1, c2, c3]


def fix_arabic_text(text: str) -> str:
    normalized = normalize_cell(text)
    if not normalized or not ARABIC_RE.search(normalized):
        return normalized

    tokens = normalized.split()
    arabic_tokens = [tok for tok in tokens if AR_TOKEN_RE.match(tok)]
    if not arabic_tokens:
        return normalized

    # Case A: heavily fragmented (letters split by spaces) => stitch + reverse.
    if len(arabic_tokens) >= 3:
        single_ratio = sum(1 for tok in arabic_tokens if len(tok) == 1) / len(arabic_tokens)
        if single_ratio >= 0.6:
            rebuilt = "".join(tok for tok in arabic_tokens)
            return rebuilt[::-1]

    # Case B: choose best orientation by readability score.
    candidates = _reverse_arabic_candidates(normalized)
    scored = [(cand, _arabic_orientation_score(cand)) for cand in candidates]
    best_text, best_score = max(scored, key=lambda item: item[1])
    base_score = scored[0][1]

    # Only change orientation if there is a clear improvement.
    if best_score >= base_score + 0.75:
        return best_text
    return normalized


def remap_by_position(row: list[str | None]) -> list[str]:
    # Normalize and drop empty fragments caused by PDF spacing.
    cells = [normalize_cell(cell) for cell in row if normalize_cell(cell)]
    if not cells:
        return []

    # Keep column mapping by position, independent from broken PDF header text.
    if len(cells) < len(COLUMNS):
        cells += [""] * (len(COLUMNS) - len(cells))
    elif len(cells) > len(COLUMNS):
        # Merge overflow into CATEGORY_DESC and preserve last 3 numeric/date fields.
        prefix = cells[:3]
        suffix = cells[-3:]
        middle = cells[3:-3]
        cells = prefix + [" ".join(middle)] + suffix

    return cells[: len(COLUMNS)]


def extract_rows(pdf_path: Path) -> list[list[str]]:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {pdf_path}")

    rows: list[list[str]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        page = pdf.pages[0]
        tables = page.extract_tables()
        if not tables:
            raise ValueError("No table found in the PDF.")

        table = tables[0]   # only one table expected
        data_rows = table[1:]  # skip malformed header row
        for row in data_rows:
            if not row:
                continue
            mapped = remap_by_position(row)
            if mapped:
                rows.append(mapped)
    return rows


def clean_dataframe(rows: list[list[str]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)

    # Strip + normalize whitespace in all cells.
    for col in df.columns:
        df[col] = df[col].astype(str).map(normalize_cell)

    # Generic Arabic cleanup/orientation fix (no hardcoded phrase mapping).
    for col in df.columns:
        mask = df[col].str.contains(ARABIC_RE, na=False)
        if mask.any():
            df.loc[mask, col] = df.loc[mask, col].map(fix_arabic_text)

    return df


def main() -> None:
    rows = extract_rows(INPUT_PDF)
    df = clean_dataframe(rows)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print("=== EXTRACTION COMPLETE ===")
    print(f"Rows extracted : {len(df)}")
    print(f"Columns        : {list(df.columns)}")
    print()
    print(df.to_string(index=False))
    print()
    print(f"Saved CSV      : {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
