#!/usr/bin/env python3
"""L1 harvest: deterministic candidate terms from a markdown page (no model).

Usage: structural_terms.py <page.md>   -> prints JSON {"terms": [{term, count, kind}]}
"""
import json
import re
import sys
from collections import Counter

STOP_CAPS = {
    "The", "This", "That", "These", "Those", "A", "An", "In", "On", "For", "And", "But", "Or",
    "If", "When", "What", "Why", "How", "We", "You", "It", "Our", "Your", "To", "Of", "With",
    "Read", "More", "Share", "Sign", "Log", "Home", "Menu", "Next", "Previous", "Copyright",
}
STOP_ACRONYMS = {"I", "OK", "AM", "PM", "US", "UK", "EU", "FAQ", "PDF", "HTML", "URL", "HTTP", "HTTPS",
                 "ISBN", "ISSN", "DOI", "S2CID", "PMID", "PMC", "OCLC"}

TOP_N = 40


def norm(t):
    return re.sub(r"\s+", " ", t.strip(" \t*_`#:.,;()[]\"'")).strip()


def extract(md):
    found = Counter()
    kinds = {}

    def add(term, kind):
        term = norm(term)
        if len(term) < 2 or len(term) > 80 or len(term.split()) > 8 or not re.search(r"[A-Za-z]{2}", term):
            return
        found[term] += 1
        # strongest signal wins: heading > bold > code > acronym > ngram
        order = ["heading", "bold", "code", "acronym", "ngram"]
        if term not in kinds or order.index(kind) < order.index(kinds[term]):
            kinds[term] = kind

    for m in re.finditer(r"^#{1,6}\s+(.+)$", md, re.M):
        add(m.group(1), "heading")
    for m in re.finditer(r"\*\*([^*\n]{2,80})\*\*", md):
        add(m.group(1), "bold")
    for m in re.finditer(r"(?<!`)`([^`\n]{2,60})`(?!`)", md):
        add(m.group(1), "code")
    for m in re.finditer(r"\b[A-Z][A-Z0-9&]{1,9}s?\b", md):
        t = m.group(0)
        if t.rstrip("s") not in STOP_ACRONYMS and not t.isdigit():
            add(t, "acronym")
    for m in re.finditer(r"\b[A-Z][a-z0-9]+(?:[- ](?:[A-Z][a-z0-9]+|of|for|and|to)){1,3}\b", md):
        words = m.group(0).split()
        if words[0] in STOP_CAPS or words[-1] in {"of", "for", "and", "to"}:
            continue
        add(m.group(0), "ngram")

    weight = {"heading": 3, "bold": 3, "code": 2, "acronym": 2, "ngram": 1}
    ranked = sorted(found, key=lambda t: (-(found[t] * weight[kinds[t]]), t))
    return [{"term": t, "count": found[t], "kind": kinds[t]} for t in ranked[:TOP_N]]


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: structural_terms.py <page.md>")
    with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
        print(json.dumps({"terms": extract(f.read())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
