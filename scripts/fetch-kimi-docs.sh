#!/usr/bin/env bash
# Fetch Kimi product docs into docs/kimi-knowledge/.
# Prefer: uv run python scripts/fetch_kimi_docs.py  (cross-platform, no pandoc).
# This shell wrapper keeps the bash entrypoint for Linux/CI with pandoc.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if command -v uv >/dev/null 2>&1; then
  exec uv run python scripts/fetch_kimi_docs.py "$@"
fi

if command -v python3 >/dev/null 2>&1; then
  exec python3 scripts/fetch_kimi_docs.py "$@"
fi

# Legacy path: curl + pandoc (noisy HTML; kept as last resort)
if ! command -v pandoc >/dev/null 2>&1; then
  echo "Need uv/python3 or pandoc. Install: https://docs.astral.sh/uv/" >&2
  exit 1
fi

mkdir -p docs/kimi-knowledge/{resources,use-cases,capabilities,showcases}

fetch() {
  local url="$1" out="$2"
  echo "curl+pandoc: $url"
  curl -fsSL -A "PalatiumAI-KimiDocsFetcher/1.0" "$url" \
    | pandoc -f html -t markdown --wrap=none -o "$out"
}

echo "Скачивание Resources..."
fetch https://www.kimi.ai/resources/ai-agent docs/kimi-knowledge/resources/ai-agent.md
fetch https://www.kimi.ai/resources/multi-agent docs/kimi-knowledge/resources/multi-agent.md
fetch https://www.kimi.ai/resources/parallel-agent docs/kimi-knowledge/resources/parallel-agent.md
fetch https://www.kimi.ai/resources/what-is-vibe-coding docs/kimi-knowledge/resources/vibe-coding.md
fetch https://www.kimi.ai/resources/how-to-build-landing-pages docs/kimi-knowledge/resources/landing-pages.md
fetch https://www.kimi.ai/resources/create-your-poster docs/kimi-knowledge/resources/poster.md
fetch https://www.kimi.ai/resources/how-to-write-a-business-proposal docs/kimi-knowledge/resources/business-proposal.md

echo "Скачивание Use Cases..."
fetch https://www.kimi.ai/use-cases/mvp-builder docs/kimi-knowledge/use-cases/mvp-builder.md
fetch https://www.kimi.ai/use-cases/portfolio-site-builder docs/kimi-knowledge/use-cases/portfolio-site-builder.md
fetch https://www.kimi.ai/use-cases/blog-site-creator docs/kimi-knowledge/use-cases/blog-site-creator.md
fetch https://www.kimi.ai/use-cases/ai-for-academic-research docs/kimi-knowledge/use-cases/academic-research.md
fetch https://www.kimi.ai/use-cases/ai-market-research docs/kimi-knowledge/use-cases/market-research.md
fetch https://www.kimi.ai/use-cases/resume-maker docs/kimi-knowledge/use-cases/resume-maker.md
fetch https://www.kimi.ai/use-cases/brochure-creator docs/kimi-knowledge/use-cases/brochure-creator.md

echo "Скачивание Capabilities..."
fetch https://www.kimi.ai/capabilities/ai-landing-page-generator docs/kimi-knowledge/capabilities/landing-page-generator.md
fetch https://www.kimi.ai/capabilities/image-to-website docs/kimi-knowledge/capabilities/image-to-website.md
fetch https://www.kimi.ai/capabilities/ai-document-generator docs/kimi-knowledge/capabilities/document-generator.md
fetch https://www.kimi.ai/capabilities/pdf-to-ppt docs/kimi-knowledge/capabilities/pdf-to-ppt.md
fetch https://www.kimi.ai/capabilities/translate-pdf docs/kimi-knowledge/capabilities/translate-pdf.md
fetch https://www.kimi.ai/capabilities/ai-python-code-generator docs/kimi-knowledge/capabilities/python-code-gen.md
fetch https://www.kimi.ai/capabilities/ai-cplusplus-code-generator docs/kimi-knowledge/capabilities/cpp-code-gen.md

echo "Скачивание Showcases..."
fetch https://www.kimi.ai/showcases/websites-agent docs/kimi-knowledge/showcases/websites-agent.md
fetch https://www.kimi.ai/showcases/agent-swarm docs/kimi-knowledge/showcases/agent-swarm.md
fetch https://www.kimi.ai/showcases/deep-research docs/kimi-knowledge/showcases/deep-research.md
fetch https://www.kimi.ai/showcases/slides docs/kimi-knowledge/showcases/slides.md
fetch https://www.kimi.ai/showcases/sheets docs/kimi-knowledge/showcases/sheets.md
fetch https://www.kimi.ai/showcases/docs docs/kimi-knowledge/showcases/docs.md
fetch https://www.kimi.ai/showcases/design docs/kimi-knowledge/showcases/design.md

echo "Готово! База знаний собрана в docs/kimi-knowledge/"
