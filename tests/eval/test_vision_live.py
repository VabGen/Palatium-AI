"""Vision (S3) live eval: does the configured alias actually *see* the fixture image?

Run (opt-in; CI never selects the ``live`` marker):

    PALATIUM_GATEWAY_URL=http://127.0.0.1:4000 \
    PALATIUM_GATEWAY_KEY=<gateway key> \
    LLM_VISION_MODEL=vision-tier \
    uv run pytest tests/eval/test_vision_live.py -m live -q

Values fall back to ``env/.env`` (the file ``scripts/dev-up.ps1`` uses); the test skips
when the gateway key or the vision alias is empty, so a plain ``pytest`` stays green and
an unconfigured checkout never pretends to have exercised vision.

What it proves: the whole chain — ``ChatMessage.image_parts`` → ``VisionImageSourcePort``
→ LiteLLM ``image_url`` part → gateway alias ``vision-tier`` → model — reaches a model
that describes the pixels. A text-only model cannot pass: the answer is a description of
the fixture (three bars, red/green/blue), and the prompt token count covers the image.

It is a *live* eval, not a unit test: the fixture is a real PNG on disk and the verdict
is the model's prose. Deterministic contracts (policy, payload, denial reasons) are pinned
in ``tests/unit/test_vision_route.py`` and ``tests/unit/test_vision_delivery_channel.py``.
"""

from __future__ import annotations

import os

from pathlib import Path
from typing import Final
from uuid import UUID, uuid5

import pytest

from pydantic import SecretStr

from palatium_ai.application.agents.harness import Harness
from palatium_ai.core.config.llm.gateway import GatewayLLMConfig
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.llm.errors import VisionImageUnavailableError
from palatium_ai.domain.llm.models import ChatMessage, ImagePart
from palatium_ai.infrastructure.llm.litellm_adapter import LiteLLMAdapter

pytestmark = [
    pytest.mark.live,
    # LiteLLM emits this while building the OpenAI payload; pytest filterwarnings=error
    # would turn it into a failed call before the model answers.
    pytest.mark.filterwarnings(
        "ignore:Item 'summary' on TypedDict class 'ChatCompletionReasoningItem':UserWarning",
    ),
]

#: Fixture created with three coloured bars on a white canvas — describable in any language.
FIXTURE_PATH: Final = Path(__file__).resolve().parents[1] / "fixtures" / "vision" / "bar_chart.png"
#: Stable id for the fixture: no attachment row exists in a live eval, and the data URL
#: map is keyed by ``ImagePart.attachment_id``.
FIXTURE_ATTACHMENT_ID: Final = uuid5(UUID(int=0), "palatium-vision-eval-bar-chart")

#: A description of *this* picture mentions one of these (EN/RU, chart or colours).
_DESCRIPTION_MARKERS: Final = (
    "chart",
    "bar",
    "graph",
    "column",
    "histogram",
    "red",
    "green",
    "blue",
    "график",
    "диаграмм",
    "гистограмм",
    "столбц",
    "красн",
    "зелён",
    "син",
)
#: "The picture is empty / I cannot see it" is the failure mode the ADR exists to prevent.
_REFUSAL_MARKERS: Final = (
    "cannot see",
    "can't see",
    "no image",
    "not able to see",
    "не вижу",
    "не могу увидеть",
    "нет изображения",
    "изображение отсутствует",
)

_LIVE_ENV_KEYS: Final = ("PALATIUM_GATEWAY_URL", "PALATIUM_GATEWAY_KEY", "LLM_VISION_MODEL")


def _load_env_file() -> None:
    """Prefer ``env/.env`` over conftest placeholders (which point at a local gateway)."""
    root = Path(__file__).resolve().parents[2]
    env_path = root / "env" / ".env"
    if not env_path.is_file():
        return
    from dotenv import dotenv_values

    example = dotenv_values(root / "env" / ".env.example")
    real = dotenv_values(env_path)
    for key in _LIVE_ENV_KEYS:
        real_value = (real.get(key) or "").strip()
        if not real_value:
            continue
        current = os.environ.get(key, "").strip()
        example_value = (example.get(key) or "").strip()
        if not current or current == example_value:
            os.environ[key] = real_value


class _FixtureImageSource:
    """``VisionImageSourcePort`` over one PNG: a live eval has no blob store or row."""

    def __init__(self, path: Path, *, mime: str) -> None:
        self._path = path
        self._mime = mime
        self._bytes = path.read_bytes()

    async def read(self, attachment_id: UUID, *, expected_mime: str) -> bytes:
        if attachment_id != FIXTURE_ATTACHMENT_ID or expected_mime != self._mime:
            raise VisionImageUnavailableError("fixture source only serves the eval image")
        return self._bytes


def _requirements() -> tuple[str, str, str]:
    """Gateway key, base URL and vision alias, or a skip explaining what is missing."""
    _load_env_file()
    key = os.environ.get("PALATIUM_GATEWAY_KEY", "").strip()
    base = os.environ.get("PALATIUM_GATEWAY_URL", "").strip() or "http://127.0.0.1:4000"
    alias = os.environ.get("LLM_VISION_MODEL", "").strip()
    if not key:
        pytest.skip("PALATIUM_GATEWAY_KEY is required for the live vision eval")
    if not alias:
        pytest.skip("LLM_VISION_MODEL is empty: the vision route is disabled (ADR 0007)")
    return key, base, alias


@pytest.mark.asyncio()
async def test_vision_model_live() -> None:
    """The vision alias describes the fixture; prompt tokens prove the image travelled."""
    key, base, alias = _requirements()
    assert FIXTURE_PATH.is_file(), f"missing vision fixture: {FIXTURE_PATH}"

    adapter = LiteLLMAdapter(
        GatewayLLMConfig(
            api_key=SecretStr(key),
            base_url=base,
            default_model=alias,
        ),
        vision_model=alias,
        image_source=_FixtureImageSource(FIXTURE_PATH, mime="image/png"),
    )
    harness = Harness(llm=adapter)
    config = AgentConfig(
        name="vision_eval",
        role="researcher",
        model_tier="mid",
        temperature=0.1,
        timeout_seconds=120,
        max_retries=1,
    )
    messages = [
        ChatMessage(role="system", content="You describe images factually and briefly."),
        ChatMessage(
            role="user",
            content="What is shown in this image? Name the shapes and colours you see.",
            image_parts=(ImagePart(attachment_id=FIXTURE_ATTACHMENT_ID, mime="image/png"),),
        ),
    ]

    completion = await harness.call_llm(config, messages, max_tokens=256)

    answer = completion.content.strip()
    lowered = answer.casefold()
    assert answer, "the vision model returned an empty description"
    assert completion.usage.prompt_tokens > 0, "an image call must bill prompt tokens; none were reported"
    refusals = [marker for marker in _REFUSAL_MARKERS if marker in lowered]
    assert not refusals, f"the model claims it cannot see the image ({refusals}): {answer}"
    assert any(marker in lowered for marker in _DESCRIPTION_MARKERS), (
        f"the answer does not describe the fixture (bars/colours/chart): {answer}"
    )
