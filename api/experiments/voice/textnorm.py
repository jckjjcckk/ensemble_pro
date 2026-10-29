"""Text normalisation for the voice eval: spoken numbers to digits, word error rate, annotation text compare.

Numbers: "thirty-four" = 34, "two hundred and three" = 203, conductor shorthand "one-twelve" = 112 (a hyphenated
unit then a tens/teen word is read as two digit groups), "one thirty" (unhyphenated) = "1 30", "1:30" = "1 30".
"""

from __future__ import annotations

import re
import unicodedata

UNITS = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9}
TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
         "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SMALL = {**UNITS, **TEENS, **TENS}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _hyphen_number(tok: str) -> str | None:
    """'thirty-four' -> '34', 'one-twelve' -> '112', 'one-sixteen' -> '116'; else None."""
    parts = tok.split("-")
    if len(parts) != 2 or not all(p in SMALL for p in parts):
        return None
    a, b = parts
    if a in TENS and b in UNITS and UNITS[b] > 0:
        return str(TENS[a] + UNITS[b])
    if a in UNITS and (b in TEENS or b in TENS):
        return f"{UNITS[a]}{SMALL[b]}"
    return None


def numbers_to_digits(tokens: list[str]) -> list[str]:
    """Collapse number-word runs into digit tokens. Unhyphenated runs follow the plain grammar
    ([units] hundred [and] [tens] [units]); anything that does not fit starts a new number."""
    out: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        h = _hyphen_number(t)
        if h is not None:
            out.append(h)
            i += 1
            continue
        if t not in SMALL:
            out.append(t)
            i += 1
            continue
        # plain grammar
        val = 0
        j = i
        if tokens[j] in UNITS and j + 1 < len(tokens) and tokens[j + 1] == "hundred":
            val = UNITS[tokens[j]] * 100
            j += 2
            if j < len(tokens) and tokens[j] == "and" and j + 1 < len(tokens) and (
                    tokens[j + 1] in SMALL or _hyphen_number(tokens[j + 1])):
                j += 1
            if j < len(tokens):
                hh = _hyphen_number(tokens[j])
                if hh is not None and len(hh) <= 2:
                    val += int(hh)
                    j += 1
                elif tokens[j] in TENS:
                    val += TENS[tokens[j]]
                    j += 1
                    if j < len(tokens) and tokens[j] in UNITS and UNITS[tokens[j]] > 0:
                        val += UNITS[tokens[j]]
                        j += 1
                elif tokens[j] in TEENS or tokens[j] in UNITS:
                    val += SMALL[tokens[j]]
                    j += 1
        elif tokens[j] in TENS:
            val = TENS[tokens[j]]
            j += 1
            if j < len(tokens) and tokens[j] in UNITS and UNITS[tokens[j]] > 0:
                val += UNITS[tokens[j]]
                j += 1
        else:
            val = SMALL[tokens[j]]
            j += 1
        out.append(str(val))
        i = j
    return out


def words(text: str) -> list[str]:
    """Lowercase word tokens with numbers as digits, for WER."""
    s = _strip_accents(text.lower())
    s = s.replace("♯", " sharp ").replace("#", " sharp ").replace("♭", " flat ")
    s = re.sub(r"(\d):(\d)", r"\1 \2", s)
    s = s.replace("–", "-").replace("—", " ")
    s = re.sub(r"[^a-z0-9'\- ]+", " ", s)
    toks = [t.strip("'-") for t in s.split()]
    return numbers_to_digits([t for t in toks if t])


def wer(ref: str, hyp: str) -> tuple[int, int]:
    """(word edits, reference length) after normalisation."""
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
            prev, d[j] = d[j], cur
    return d[len(h)], len(r)


def annotation_key(text: str) -> str:
    """Exact-match key for the stand text: case, accents, dashes, punctuation and spoken numbers folded."""
    s = _strip_accents(text.lower()).replace("♯", "#").replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*-\s*", "-", s)
    s = re.sub(r"[^a-z0-9#\- ]+", " ", s)
    return " ".join(numbers_to_digits(s.split()))
