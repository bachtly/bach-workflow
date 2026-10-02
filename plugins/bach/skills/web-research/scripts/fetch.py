#!/usr/bin/env python3
"""Fetch one URL to local markdown (no model), plus L1 structural terms.

Usage:
  fetch.py <run_dir> <sid> <url>               curl-style fetch -> pages/<sid>.md
  fetch.py <run_dir> <sid> <url> --from-file   page was already written by the agent (WebFetch fallback)

Writes pages/<sid>.md, fetch/<sid>.json, notes/<sid>.struct.json, then rebuilds the CSVs.
Prints one JSON line. Exit codes:
  0  page usable
  3  failed, agent should fall back to WebFetch
  4  failed, do NOT fall back (PDFs: WebFetch would hand back a lossy small-model rendition)
"""
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zlib
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import record  # noqa: E402
import structural_terms  # noqa: E402

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
TIMEOUT = 20
MAX_BYTES = 25_000_000
MAX_CHARS = 500_000  # safety valve only; real pages rarely get near it
PDF_MIN_CHARS = 200
INSTALL_HINT = "install poppler for pdftotext: brew install poppler (macOS) / apt install poppler-utils"
MIN_CHARS = 600
BLOCK_MARKERS = (
    "just a moment...", "enable javascript", "checking your browser", "access denied",
    "verify you are human", "captcha", "please turn javascript on", "attention required",
)

# Never content.
HARD_SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "canvas", "select", "button", "nav"}
# Boilerplate only when OUTSIDE <main>/<article> (an article's own <header>/<aside> is content).
SOFT_SKIP = {"header", "footer", "aside", "form"}
SKIP_ROLES = {"navigation", "banner", "contentinfo", "search"}
POPUP_RE = re.compile(r"cookie|consent|gdpr|newsletter-signup|modal-backdrop", re.I)
BLOCK = {"p", "div", "section", "article", "main", "br", "tr", "table", "blockquote", "figure",
         "figcaption", "dl", "dt", "dd", "ul", "ol"}
# If boilerplate stripping removes more than this share of the text, keep the unstripped text instead.
MIN_KEEP_RATIO = 0.5


class MD(HTMLParser):
    """HTML -> markdown. Emits two streams: `out` (boilerplate stripped) and `raw` (only HARD_SKIP removed)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.raw = [], []
        self.hard = 0                         # depth inside HARD_SKIP
        self.soft_tag, self.soft_depth = None, 0  # element currently skipped as boilerplate
        self.content = 0                      # depth inside <main>/<article>
        self.pre = 0
        self.title, self.in_title = "", False

    def emit(self, s):
        self.raw.append(s)
        if not self.soft_tag:
            self.out.append(s)

    def is_boilerplate(self, tag, attrs):
        a = dict(attrs)
        if (a.get("role") or "").lower() in SKIP_ROLES:
            return True
        if POPUP_RE.search((a.get("id") or "") + " " + (a.get("class") or "")):
            return True
        return tag in SOFT_SKIP and not self.content

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag in HARD_SKIP:
            self.hard += 1
            return
        if self.hard:
            return
        if self.soft_tag:
            if tag == self.soft_tag:
                self.soft_depth += 1
        elif self.is_boilerplate(tag, attrs):
            self.soft_tag, self.soft_depth = tag, 1
        if tag in ("main", "article"):
            self.content += 1
        if re.fullmatch(r"h[1-6]", tag):
            self.emit("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.emit("\n- ")
        elif tag in ("strong", "b"):
            self.emit("**")
        elif tag == "code" and not self.pre:
            self.emit("`")
        elif tag == "pre":
            self.pre += 1
            self.emit("\n```\n")
        elif tag in ("td", "th"):
            self.emit(" | ")
        elif tag in BLOCK:
            self.emit("\n\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in HARD_SKIP:
            self.hard = max(0, self.hard - 1)
            return
        if self.hard:
            return
        if re.fullmatch(r"h[1-6]", tag):
            self.emit("\n")
        elif tag in ("strong", "b"):
            self.emit("**")
        elif tag == "code" and not self.pre:
            self.emit("`")
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
            self.emit("\n```\n")
        elif tag in BLOCK:
            self.emit("\n")
        if tag in ("main", "article"):
            self.content = max(0, self.content - 1)
        if self.soft_tag and tag == self.soft_tag:
            self.soft_depth -= 1
            if self.soft_depth <= 0:
                self.soft_tag = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.hard:
            return
        self.emit(data if self.pre else re.sub(r"\s+", " ", data))


def tidy(text):
    text = re.sub(r"\*\*\s*\*\*", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_md(html):
    """Returns (title, markdown, mode). Falls back to the unstripped text when stripping looks too aggressive
    (e.g. an unclosed <header> swallowing the page)."""
    p = MD()
    p.feed(html)
    p.close()
    stripped, raw = tidy("".join(p.out)), tidy("".join(p.raw))
    if raw and len(stripped) < MIN_KEEP_RATIO * len(raw):
        return p.title.strip(), raw, "raw"
    return p.title.strip(), stripped, "stripped"


def download(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read(MAX_BYTES + 1)
        enc = (r.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip":
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            raw = zlib.decompress(raw)
        ctype = (r.headers.get("Content-Type") or "").lower()
        charset = r.headers.get_content_charset() or "utf-8"
        return raw, ctype, charset, r.status


def is_pdf_url(url):
    return bool(re.search(r"\.pdf($|[?#])", url, re.I))


def pdf_to_text(raw, path):
    tool = shutil.which("pdftotext")
    if not tool:
        return None
    tmp = path + ".pdf"
    with open(tmp, "wb") as f:
        f.write(raw)
    try:
        return subprocess.run([tool, "-layout", tmp, "-"], capture_output=True, text=True, timeout=60).stdout
    finally:
        os.remove(tmp)


def finish(run_dir, sid, url, meta, code):
    record.write_json(os.path.join(run_dir, "fetch", sid + ".json"), meta)
    page = os.path.join(run_dir, "pages", sid + ".md")
    if meta["status"] == "ok":
        with open(page, encoding="utf-8", errors="replace") as f:
            struct = {"sid": sid, "terms": structural_terms.extract(f.read())}
        record.write_json(os.path.join(run_dir, "notes", sid + ".struct.json"), struct)
        meta["l1_terms"] = len(struct["terms"])
    record.rebuild(run_dir)
    print(json.dumps(meta))
    sys.exit(code)


def main():
    args = sys.argv[1:]
    from_file = "--from-file" in args
    args = [a for a in args if a != "--from-file"]
    if len(args) != 3:
        sys.exit("usage: fetch.py <run_dir> <sid> <url> [--from-file]")
    run_dir, sid, url = args
    for d in ("pages", "fetch", "notes"):
        os.makedirs(os.path.join(run_dir, d), exist_ok=True)
    page = os.path.join(run_dir, "pages", sid + ".md")
    meta = {"sid": sid, "url": url, "method": "webfetch" if from_file else "curl",
            "status": "failed", "reason": "", "bytes": 0, "chars": 0, "title": ""}

    if from_file:
        if not os.path.exists(page):
            meta["reason"] = "page file missing"
            finish(run_dir, sid, url, meta, 3)
        with open(page, encoding="utf-8", errors="replace") as f:
            text = f.read()
        meta.update(chars=len(text), bytes=len(text.encode()))
        if len(text) < MIN_CHARS // 2:
            meta["reason"] = "webfetch returned too little text"
            finish(run_dir, sid, url, meta, 3)
        meta["status"] = "ok"
        finish(run_dir, sid, url, meta, 0)

    # A PDF never goes to the WebFetch fallback: fail loudly instead (exit 4).
    pdf_fail = 4 if is_pdf_url(url) else 3
    try:
        raw, ctype, charset, status = download(url)
    except urllib.error.HTTPError as e:
        meta["reason"] = f"http {e.code}"
        finish(run_dir, sid, url, meta, pdf_fail)
    except Exception as e:  # timeouts, TLS, DNS
        meta["reason"] = type(e).__name__ + ": " + str(e)[:120]
        finish(run_dir, sid, url, meta, pdf_fail)

    meta["bytes"] = len(raw)
    if len(raw) > MAX_BYTES:
        meta["reason"] = f"too large (> {MAX_BYTES} bytes)"
        finish(run_dir, sid, url, meta, pdf_fail)

    if "pdf" in ctype or raw[:5] == b"%PDF-" or is_pdf_url(url):
        meta["format"] = "pdf"
        text = pdf_to_text(raw, page)
        if text is None:
            meta["reason"] = "pdftotext missing; " + INSTALL_HINT
            finish(run_dir, sid, url, meta, 4)
        if len(text.strip()) < PDF_MIN_CHARS:
            meta["reason"] = "pdf has no text layer (scanned?)"
            finish(run_dir, sid, url, meta, 4)
        title = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")[:200]
    else:
        if "html" in ctype or "xml" in ctype or not ctype:
            title, text, meta["mode"] = html_to_md(raw.decode(charset, errors="replace"))
        else:
            title, text = "", raw.decode(charset, errors="replace")
        low = text[:3000].lower()
        if len(text) < MIN_CHARS:
            meta["reason"] = f"too little text ({len(text)} chars), likely JS-rendered"
            finish(run_dir, sid, url, meta, 3)
        if len(text) < 5000 and any(m in low for m in BLOCK_MARKERS):
            meta["reason"] = "bot wall"
            finish(run_dir, sid, url, meta, 3)

    meta["truncated"] = len(text) > MAX_CHARS
    if meta["truncated"]:
        text = text[:MAX_CHARS] + "\n\n[truncated at %d chars]" % MAX_CHARS
    header = f"# {title}\n\nSource: {url}\n\n" if title else f"Source: {url}\n\n"
    with open(page, "w", encoding="utf-8") as f:
        f.write(header + text)
    meta.update(status="ok", title=title[:200], chars=len(text))
    finish(run_dir, sid, url, meta, 0)


if __name__ == "__main__":
    main()
