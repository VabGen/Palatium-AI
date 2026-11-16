#!/usr/bin/env python3
"""Fetch Kimi product pages into docs/kimi-knowledge/ (local agent SoT).

Windows-friendly alternative to scripts/fetch-kimi-docs.sh when pandoc/WSL
are unavailable. Prefer pandoc when present; otherwise stdlib HTML→Markdown.

Usage:
  uv run python scripts/fetch_kimi_docs.py
  py -3 scripts/fetch_kimi_docs.py
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "docs" / "kimi-knowledge"
USER_AGENT = "PalatiumAI-KimiDocsFetcher/1.0 (+local agent knowledge; contact via repo maintainers)"


@dataclass(frozen=True, slots=True)
class Page:
    category: str
    slug: str
    url: str
    outfile: str


PAGES: tuple[Page, ...] = (
    # Resources
    Page("resources", "ai-agent", "https://www.kimi.ai/resources/ai-agent", "ai-agent.md"),
    Page(
        "resources",
        "multi-agent",
        "https://www.kimi.ai/resources/multi-agent",
        "multi-agent.md",
    ),
    Page(
        "resources",
        "parallel-agent",
        "https://www.kimi.ai/resources/parallel-agent",
        "parallel-agent.md",
    ),
    Page(
        "resources",
        "vibe-coding",
        "https://www.kimi.ai/resources/what-is-vibe-coding",
        "vibe-coding.md",
    ),
    Page(
        "resources",
        "landing-pages",
        "https://www.kimi.ai/resources/how-to-build-landing-pages",
        "landing-pages.md",
    ),
    Page(
        "resources",
        "poster",
        "https://www.kimi.ai/resources/create-your-poster",
        "poster.md",
    ),
    Page(
        "resources",
        "business-proposal",
        "https://www.kimi.ai/resources/how-to-write-a-business-proposal",
        "business-proposal.md",
    ),
    # Use cases
    Page(
        "use-cases",
        "mvp-builder",
        "https://www.kimi.ai/use-cases/mvp-builder",
        "mvp-builder.md",
    ),
    Page(
        "use-cases",
        "portfolio-site-builder",
        "https://www.kimi.ai/use-cases/portfolio-site-builder",
        "portfolio-site-builder.md",
    ),
    Page(
        "use-cases",
        "blog-site-creator",
        "https://www.kimi.ai/use-cases/blog-site-creator",
        "blog-site-creator.md",
    ),
    Page(
        "use-cases",
        "academic-research",
        "https://www.kimi.ai/use-cases/ai-for-academic-research",
        "academic-research.md",
    ),
    Page(
        "use-cases",
        "market-research",
        "https://www.kimi.ai/use-cases/ai-market-research",
        "market-research.md",
    ),
    Page(
        "use-cases",
        "resume-maker",
        "https://www.kimi.ai/use-cases/resume-maker",
        "resume-maker.md",
    ),
    Page(
        "use-cases",
        "brochure-creator",
        "https://www.kimi.ai/use-cases/brochure-creator",
        "brochure-creator.md",
    ),
    # Capabilities
    Page(
        "capabilities",
        "landing-page-generator",
        "https://www.kimi.ai/capabilities/ai-landing-page-generator",
        "landing-page-generator.md",
    ),
    Page(
        "capabilities",
        "image-to-website",
        "https://www.kimi.ai/capabilities/image-to-website",
        "image-to-website.md",
    ),
    Page(
        "capabilities",
        "document-generator",
        "https://www.kimi.ai/capabilities/ai-document-generator",
        "document-generator.md",
    ),
    Page(
        "capabilities",
        "pdf-to-ppt",
        "https://www.kimi.ai/capabilities/pdf-to-ppt",
        "pdf-to-ppt.md",
    ),
    Page(
        "capabilities",
        "translate-pdf",
        "https://www.kimi.ai/capabilities/translate-pdf",
        "translate-pdf.md",
    ),
    Page(
        "capabilities",
        "python-code-gen",
        "https://www.kimi.ai/capabilities/ai-python-code-generator",
        "python-code-gen.md",
    ),
    Page(
        "capabilities",
        "cpp-code-gen",
        "https://www.kimi.ai/capabilities/ai-cplusplus-code-generator",
        "cpp-code-gen.md",
    ),
    # Showcases
    Page(
        "showcases",
        "websites-agent",
        "https://www.kimi.ai/showcases/websites-agent",
        "websites-agent.md",
    ),
    Page(
        "showcases",
        "agent-swarm",
        "https://www.kimi.ai/showcases/agent-swarm",
        "agent-swarm.md",
    ),
    Page(
        "showcases",
        "deep-research",
        "https://www.kimi.ai/showcases/deep-research",
        "deep-research.md",
    ),
    Page("showcases", "slides", "https://www.kimi.ai/showcases/slides", "slides.md"),
    Page("showcases", "sheets", "https://www.kimi.ai/showcases/sheets", "sheets.md"),
    Page("showcases", "docs", "https://www.kimi.ai/showcases/docs", "docs.md"),
    Page("showcases", "design", "https://www.kimi.ai/showcases/design", "design.md"),
)

_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "svg",
        "path",
        "nav",
        "footer",
        "header",
        "iframe",
        "template",
    }
)
_BLOCK_TAGS = frozenset({"p", "div", "section", "article", "main", "li", "tr", "br", "hr"})
_HEADING = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


class _HtmlToMarkdown(HTMLParser):
    """Best-effort HTML→Markdown for SSR landing pages (no pandoc)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._title: str | None = None
        self._description: str | None = None
        self._in_title = False
        self._href: str | None = None
        self._capture_link = False
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}
        if tag in _SKIP_TAGS or attr.get("role") in {"banner", "navigation", "contentinfo"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "meta" and attr.get("name", "").lower() == "description":
            self._description = attr.get("content") or None
            return
        if tag in _HEADING:
            self._parts.append(f"\n\n{_HEADING[tag]} ")
            return
        if tag == "br":
            self._parts.append("\n")
            return
        if tag == "hr":
            self._parts.append("\n\n---\n\n")
            return
        if tag in {"ul", "ol"}:
            self._parts.append("\n")
            return
        if tag == "li":
            self._parts.append("\n- ")
            return
        if tag == "a" and attr.get("href"):
            self._href = attr["href"]
            self._capture_link = True
            self._link_text = []
            return
        if tag in {"strong", "b"}:
            self._parts.append("**")
            return
        if tag in {"em", "i"}:
            self._parts.append("*")
            return
        if tag == "code":
            self._parts.append("`")
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
            return
        if tag == "a" and self._capture_link:
            text = "".join(self._link_text).strip() or self._href or ""
            href = self._href or ""
            if href.startswith("/") and not href.startswith("//"):
                href = f"https://www.kimi.ai{href}"
            self._parts.append(f"[{text}]({href})")
            self._capture_link = False
            self._href = None
            self._link_text = []
            return
        if tag in {"strong", "b"}:
            self._parts.append("**")
            return
        if tag in {"em", "i"}:
            self._parts.append("*")
            return
        if tag == "code":
            self._parts.append("`")
            return
        if tag in _HEADING or tag in _BLOCK_TAGS or tag in {"ul", "ol", "li"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip("\n")
        if not text.strip():
            return
        if self._in_title:
            self._title = html.unescape(text.strip())
            return
        if self._capture_link:
            self._link_text.append(text)
            return
        self._parts.append(text)

    def to_markdown(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t]+\n", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def _fetch(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _via_pandoc(html_text: str) -> str | None:
    pandoc = shutil.which("pandoc")
    if not pandoc:
        return None
    proc = subprocess.run(  # noqa: S603 — pandoc path from which()
        [pandoc, "-f", "html", "-t", "markdown", "--wrap=none"],
        input=html_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _via_stdlib(html_text: str) -> tuple[str, str | None, str | None]:
    parser = _HtmlToMarkdown()
    parser.feed(html_text)
    parser.close()
    return parser.to_markdown(), parser._title, parser._description


def _frontmatter(*, url: str, title: str | None, fetched_at: str, converter: str) -> str:
    safe_title = (title or "").replace('"', "'")
    lines = [
        "---",
        f'source_url: "{url}"',
        f'fetched_at: "{fetched_at}"',
        f'converter: "{converter}"',
        'license_note: "Moonshot/Kimi site content; local mirror for Cursor agents only"',
    ]
    if safe_title:
        lines.append(f'title: "{safe_title}"')
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def fetch_page(page: Page, *, timeout: float, force: bool) -> Path:
    dest_dir = OUT_ROOT / page.category
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / page.outfile
    if dest.exists() and not force and dest.stat().st_size > 200:
        print(f"skip (exists): {dest.relative_to(ROOT)}")
        return dest

    print(f"fetch: {page.url}")
    try:
        html_text = _fetch(page.url, timeout=timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)
        raise

    fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = _via_pandoc(html_text)
    title: str | None = None
    description: str | None = None
    if body is None:
        body, title, description = _via_stdlib(html_text)
        converter = "stdlib-html-parser"
    else:
        converter = "pandoc"
        # Still parse meta for frontmatter
        _, title, description = _via_stdlib(html_text)

    if description and description not in body:
        body = f"> {description}\n\n{body}"

    content = _frontmatter(url=page.url, title=title, fetched_at=fetched_at, converter=converter)
    content += f"# {title or page.slug}\n\n" if title else f"# {page.slug}\n\n"
    content += body
    content += "\n"
    dest.write_text(content, encoding="utf-8")
    print(f"  → {dest.relative_to(ROOT)} ({len(content)} chars, {converter})")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if target markdown already exists",
    )
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    failures = 0
    for page in PAGES:
        try:
            fetch_page(page, timeout=args.timeout, force=args.force)
        except urllib.error.URLError, TimeoutError, OSError:
            failures += 1

    print(f"Done. failures={failures} out_dir={OUT_ROOT.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
