"""The widget's delivery contract is wiring, not prose (020, 050, 084).

Every item below is enforced somewhere already, yet each is one deleted line away
from silently disappearing, and the failure modes are all *quiet*:

* ``.gitattributes`` pins ``web/**`` to LF. This is not tidiness: the CEM analyzer
  embeds the JSDoc of ``src/widget.tsx`` verbatim — line endings included — into
  ``custom-elements.json``. With ``core.autocrlf=true`` (the setting on the dev
  machine where this was written) a CRLF checkout regenerates a *different* manifest,
  so ``npm run cem:check`` fails locally while CI, which checks out LF, stays green.
  The rule keeps the two environments agreeing.
* ``custom-elements.json`` is the contract the EDMS team reads (tag, attributes,
  events, ``::part``). Renaming a part is a breaking change for a host that styles
  through it, so the manifest is asserted, not just generated.
* ``vite.config.wc.ts`` must stay a single-file IIFE: the host loads exactly one
  ``<script>``, so a dynamic ``import()`` or ``manualChunks`` would ship an artifact
  the integration cannot use.
* The token belongs in memory only (W3). A ``localStorage`` write is invisible in
  review and only shows up as a leaked credential in production.
"""

from __future__ import annotations

import json
import re

from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "web"
WIDGET_SRC = WEB_ROOT / "src"
GITATTRIBUTES = REPO_ROOT / ".gitattributes"
WIDGET_MANIFEST = WEB_ROOT / "custom-elements.json"
WIDGET_PACKAGE = WEB_ROOT / "package.json"
WIDGET_VITE_CONFIG = WEB_ROOT / "vite.config.wc.ts"
RELEASE_SCRIPT = WEB_ROOT / "scripts" / "widget-release.mjs"

# The element contract the host codes against; see docs/embedded-assistant.md §2.
EXPECTED_TAG = "palatium-assistant"
EXPECTED_PARTS = {"launcher", "shell", "header", "transcript", "composer", "close"}
EXPECTED_READY_EVENT = "palatium:ready"
# The host can only learn the thread id from this event: nothing in the widget may
# persist it (see ``FORBIDDEN_IN_WIDGET``), so dropping the event silently turns
# every page reload into "the dialogue started over".
EXPECTED_THREAD_EVENT = "sed:thread-changed"

# Patterns that must never reach the runtime: token/thread persistence and a reload
# of the EDMS page (the host must survive a "new chat").
FORBIDDEN_IN_WIDGET = ("localStorage", "sessionStorage", "document.cookie", "location.reload")


def _read_json(path: Path) -> dict[str, Any]:
    # json.loads returns Any: cast keeps mypy --strict's warn_return_any quiet without
    # pretending the shape is validated here (the tests assert the fields they need).
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _declaration(manifest: dict[str, Any]) -> dict[str, Any]:
    declarations = [
        declaration
        for module in manifest["modules"]
        for declaration in module.get("declarations", [])
        if declaration.get("customElement") is True
    ]
    assert len(declarations) == 1, f"expected exactly one custom element, got {len(declarations)}"
    return cast("dict[str, Any]", declarations[0])


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Executable lines only: comments explain the bans, so they must not trip them."""
    return [
        (number, line)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if not line.strip().startswith(("//", "/*", "*", "*/"))
    ]


def test_gitattributes_pins_frontend_to_lf() -> None:
    """A CRLF checkout changes the generated CEM, so the gate must not depend on it."""
    rules = {
        line.split()[0]: line.split()[1:]
        for line in GITATTRIBUTES.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    web_rule = next((attrs for pattern, attrs in rules.items() if pattern.startswith("web/")), None)
    assert web_rule is not None, ".gitattributes must pin web/** (see this module's docstring)"
    assert "eol=lf" in web_rule, f"web/** must be LF, found: {web_rule}"


def test_widget_manifest_declares_the_public_contract() -> None:
    """Tag, attributes, events and ``::part`` names are what the host writes code against."""
    element = _declaration(_read_json(WIDGET_MANIFEST))

    assert element["tagName"] == EXPECTED_TAG
    attributes = {attribute["name"] for attribute in element.get("attributes", [])}
    assert {"lang", "collapsed"} <= attributes, f"host-facing attributes changed: {attributes}"

    events = {event.get("name") for event in element.get("events", [])}
    assert EXPECTED_READY_EVENT in events, f"hosts must learn when to send context: {events}"
    assert EXPECTED_THREAD_EVENT in events, (
        f"the host persists the dialogue thread from this event alone; without it a reload loses it: {events}"
    )

    parts = {part["name"] for part in element.get("cssParts", [])}
    assert parts == EXPECTED_PARTS, f"::part() is host-facing API; got {sorted(parts)}"


def test_package_scripts_wire_the_delivery_gates() -> None:
    """Build → SRI/budget manifest → verification, plus the manifest pointer for tooling."""
    package = _read_json(WIDGET_PACKAGE)
    scripts = package["scripts"]

    assert "widget-release.mjs" in scripts["build:widget"], "SRI and budget gate must run with the build"
    assert "--verify" in scripts["verify:widget"], "the recorded digest must be checkable"
    assert "git diff" in scripts["cem:check"], "manifest drift must fail the gate"
    assert package["customElements"] == "custom-elements.json"

    release_source = RELEASE_SCRIPT.read_text(encoding="utf-8")
    assert "sha384" in release_source, "SRI must stay sha384, as documented for the host"
    assert "BUDGET_KIB" in release_source, "the bundle budget must be enforced, not remembered"


def test_widget_build_stays_single_file_with_hashed_name() -> None:
    """One ``<script>`` for the host: no code splitting, and a name that carries version + hash."""
    lines = dict(_code_lines(WIDGET_VITE_CONFIG))
    source = "\n".join(lines.values())

    assert "formats: ['iife']" in source
    assert "inlineDynamicImports: true" in source
    assert "manualChunks" not in source, "chunking is incompatible with the single-file IIFE contract"
    assert re.search(r"v\$\{version\}\.\[hash\]", source), "artifact name must embed semver and content hash"


def test_widget_sources_keep_the_token_in_memory() -> None:
    """Nothing in the runtime may persist a token/thread or reload the EDMS page (W3, 020)."""
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{number}: {pattern}"
        for path in sorted(WIDGET_SRC.rglob("*"))
        if path.suffix in {".ts", ".tsx"}
        for number, line in _code_lines(path)
        for pattern in FORBIDDEN_IN_WIDGET
        if pattern in line
    ]
    assert not offenders, "token/thread storage or page reload returned:\n" + "\n".join(offenders)
