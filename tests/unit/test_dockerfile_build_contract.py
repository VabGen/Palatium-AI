"""The API image must contain an importable ``palatium_ai`` (035, 050, 075).

This is a regression guard for a failure that cost hours because it was invisible: the
image built *successfully*, started, and then died in ``docker-entrypoint.sh`` with
``ModuleNotFoundError: No module named 'palatium_ai'``.

The chain was:

1. ``pyproject.toml`` declares ``license-files = ["LICENSE"]`` for the root package.
2. ``Dockerfile`` copied ``pyproject.toml poetry.lock README.md`` but not ``LICENSE``.
3. ``poetry install`` therefore failed while building the root project — which it does
   *last*, after all third-party dependencies are already in the venv.
4. A ``|| true`` that was meant to make ``__pycache__`` cleanup best-effort also terminated
   the whole ``&&`` chain, so the failed install never failed the build.

Everything here is asserted against the Dockerfile text, because the defect is a *wiring*
defect: a runtime check is too late (the container is already broken) and a build check
needs a multi-minute image build. The assertions are narrow on purpose — they pin the four
links of that chain, not a particular formatting of the file.
"""

from __future__ import annotations

import re

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _REPO_ROOT / "Dockerfile"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

# The `RUN` that installs the root project. Matched loosely (`poetry install`) so a change of
# flags does not silently stop covering the guard, and anchored on the import assertion below.
_INSTALL_RUN_RE = re.compile(r"poetry install")


def _dockerfile_text() -> str:
    return _DOCKERFILE.read_text(encoding="utf-8")


def _logical_lines(text: str) -> list[str]:
    """Join backslash continuations: a `RUN` block is one logical line, not twelve."""
    joined: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            buffer += stripped[:-1] + " "
            continue
        joined.append(buffer + stripped)
        buffer = ""
    if buffer:
        joined.append(buffer)
    return joined


def _install_run() -> str:
    """Return the logical line that installs dependencies and the root project."""
    candidates = [line for line in _logical_lines(_dockerfile_text()) if _INSTALL_RUN_RE.search(line)]
    assert candidates, "no `poetry install` RUN found in the Dockerfile"
    # The install RUN is the one that also asserts the root import.
    for candidate in candidates:
        if "import palatium_ai" in candidate:
            return candidate
    raise AssertionError(
        "the `poetry install` RUN never asserts `import palatium_ai`: the root package can "
        "fail to build and the image will still be produced"
    )


def test_pyproject_root_package_declares_a_license_file() -> None:
    """Premise of the whole bug: Poetry refuses to build the root project without it."""
    text = _PYPROJECT.read_text(encoding="utf-8")

    assert re.search(r'^license-files\s*=\s*\["LICENSE"\]', text, re.MULTILINE), (
        "pyproject no longer declares license-files; re-check that the Dockerfile still needs COPY LICENSE"
    )


def test_dockerfile_copies_every_file_the_root_build_needs() -> None:
    """`LICENSE` must reach the build stage, or `poetry install` fails building the root."""
    text = _dockerfile_text()

    copy_lines = [line for line in text.splitlines() if line.strip().startswith("COPY")]
    assert any("LICENSE" in line for line in copy_lines), (
        'LICENSE is not COPYed into the image while pyproject declares license-files=["LICENSE"]'
    )

    for required in ("pyproject.toml", "poetry.lock", "README.md", "LICENSE"):
        assert any(required in line for line in copy_lines), f"{required} is not COPYed anywhere"


def test_install_run_asserts_the_root_package_imports() -> None:
    """A venv without the root package must fail the build, not the container."""
    install = _install_run()

    assert "import palatium_ai" in install, "the install step does not assert `import palatium_ai`"


def test_graphiti_extra_is_verified_when_requested() -> None:
    """`WITH_GRAPHITI=1` promises a working graph backend; an unverified pip install breaks it."""
    install = _install_run()

    assert "graphiti-core" in install, "the graphiti extra is no longer installed"
    assert "import graphiti_core" in install, "graphiti is installed but never verified"


def test_attachments_runtime_installs_tesseract_when_requested() -> None:
    """WITH_ATTACHMENTS=1 must ship the tesseract binary, not only Python OCR clients."""
    text = _dockerfile_text()
    assert "tesseract-ocr" in text, "Dockerfile never installs tesseract-ocr"
    assert "tesseract-ocr-rus" in text, "Russian tessdata missing for eng+rus OCR"
    assert "ARG WITH_ATTACHMENTS" in text
    # Runtime stage must see the ARG — builder-only install leaves the binary out of the image.
    runtime_block = text.split("FROM base AS runtime", 1)[1].split("FROM builder AS test", 1)[0]
    assert "WITH_ATTACHMENTS" in runtime_block
    assert "tesseract-ocr" in runtime_block


def test_attachments_builder_verifies_ocr_python_extras() -> None:
    """Poetry ``attachments`` group must actually expose Pillow/pytesseract/pymupdf."""
    install = _install_run()
    assert "import PIL, pytesseract, fitz" in install, (
        "WITH_ATTACHMENTS=1 installs the group but never asserts OCR Python extras"
    )


def test_no_bare_trailing_or_true_can_hide_a_failed_install() -> None:
    """The specific trap: `A && B && cleanup || true` reports success when A or B failed.

    A `|| true` is only acceptable when it is scoped to a single best-effort command, i.e.
    wrapped in `{ ... || true; }`, or when it lives in its own `RUN`.
    """
    for run in _logical_lines(_dockerfile_text()):
        if "poetry install" not in run:
            continue
        ungrouped = [
            segment.strip()
            for segment in run.split("|| true")
            # A grouped `{ ... || true; }` segment ends with `; }` and is safe.
            if not segment.rstrip().endswith("; }")
        ]
        assert len(ungrouped) <= 1, (
            f"a `|| true` is still chained onto the install RUN and can swallow a failed `poetry install`: {run}"
        )


@pytest.mark.parametrize("stage", ("builder", "runtime"))
def test_dependency_install_happens_in_a_reusable_stage(stage: str) -> None:
    """Sanity check that the fix stayed in the stage where the root project is actually built."""
    text = _dockerfile_text()

    assert re.search(rf"^FROM\s+\S+\s+AS\s+{stage}\s*$", text, re.MULTILINE), f"stage {stage} disappeared"
    assert _INSTALL_RUN_RE.search(text), "the dependency install step disappeared"
