"""Vision contract: image parts, admission policy, fail-closed adapter (ADR 0007).

What is pinned here:

* images live on the message as an ``ImagePart`` reference — no base64 in ``content``;
* images are only legal on user turns (a system/assistant image would bypass the
  prompt-injection gate the attachment pipeline owns);
* the admission policy is deterministic and fail-closed: mime → size → PII → config;
* the adapter rejects a part that was never resolved instead of dropping it, and an
  image call never fails over to a text provider (typed vision error, breaker intact).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from pydantic import ValidationError

from palatium_ai.core.config.llm import TierBinding
from palatium_ai.core.resilience import CircuitOpenError
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.llm.errors import VisionUnsupportedError
from palatium_ai.domain.llm.models import ChatMessage, ImagePart, LLMCompletion
from palatium_ai.domain.policies import VisionDecision, VisionPolicy
from palatium_ai.infrastructure.llm.factory import LLMClientFactory
from palatium_ai.infrastructure.llm.litellm_adapter import _to_litellm_messages

_MAX_BYTES = 10 * 1024 * 1024


def _image(mime: str = "image/png") -> ImagePart:
    return ImagePart(attachment_id=uuid4(), mime=mime)  # type: ignore[arg-type]


def _messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="see attached", image_parts=(_image(),))]


# --- contract -----------------------------------------------------------------


def test_image_part_rejects_unlisted_mime() -> None:
    with pytest.raises(ValidationError):
        ImagePart(attachment_id=uuid4(), mime="image/gif")  # type: ignore[arg-type]


def test_message_is_text_only_by_default() -> None:
    assert ChatMessage(role="user", content="hi").image_parts == ()


def test_user_message_carries_images() -> None:
    part = _image()
    message = ChatMessage(role="user", content="what is on this chart?", image_parts=(part,))
    assert message.image_parts == (part,)


@pytest.mark.parametrize("role", ("system", "assistant", "tool"))
def test_images_are_rejected_outside_user_turns(role: str) -> None:
    with pytest.raises(ValidationError, match="only allowed on user messages"):
        ChatMessage(role=role, content="x", image_parts=(_image(),))  # type: ignore[arg-type]


# --- admission policy ---------------------------------------------------------


def _decide(
    *,
    mime_type: str = "image/png",
    size_bytes: int = 1024,
    contains_pii: bool = False,
    vision_model: str | None = "vision-alias",
    max_image_bytes: int = _MAX_BYTES,
) -> VisionDecision:
    return VisionPolicy.decide(
        mime_type=mime_type,
        size_bytes=size_bytes,
        contains_pii=contains_pii,
        vision_model=vision_model,
        max_image_bytes=max_image_bytes,
    )


def test_supported_image_is_allowed() -> None:
    decision = _decide()
    assert decision.allowed is True
    assert decision.reason is None


def test_mime_parameters_and_case_are_normalised() -> None:
    assert _decide(mime_type=" IMAGE/PNG; charset=binary ").allowed is True


@pytest.mark.parametrize("mime_type", ("image/gif", "application/pdf", "text/plain", ""))
def test_unsupported_mime_is_denied(mime_type: str) -> None:
    assert _decide(mime_type=mime_type).reason == "unsupported_mime"


def test_empty_blob_is_denied() -> None:
    assert _decide(size_bytes=0).reason == "image_empty"


def test_oversized_image_is_denied() -> None:
    assert _decide(size_bytes=_MAX_BYTES + 1).reason == "image_too_large"


def test_pii_is_denied_by_default() -> None:
    # No "allow pii" flag on purpose: enabling it is an owner decision, not config drift.
    assert _decide(contains_pii=True).reason == "pii_blocked"


def test_missing_model_is_denied() -> None:
    assert _decide(vision_model=None).reason == "vision_not_configured"
    assert _decide(vision_model="   ").reason == "vision_not_configured"


def test_structural_reason_wins_over_pii() -> None:
    assert _decide(mime_type="image/gif", contains_pii=True).reason == "unsupported_mime"


def test_pii_reason_wins_over_configuration() -> None:
    assert _decide(contains_pii=True, vision_model=None).reason == "pii_blocked"


# --- adapter + fallback chain -------------------------------------------------


def test_adapter_rejects_image_parts_instead_of_dropping_them() -> None:
    with pytest.raises(VisionUnsupportedError):
        _to_litellm_messages(_messages())


class _Port:
    """Minimal LLMPort double: ``error`` decides the failure this provider reports."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    async def generate(self, messages: list[ChatMessage], **kwargs: Any) -> LLMCompletion:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMCompletion(content="ok", model="m")


def _factory_with_ports(
    ports: dict[str, _Port],
    *,
    circuit_failures_to_open: int = 2,
) -> LLMClientFactory:
    chain = tuple(ports)
    llm = SimpleNamespace(
        default_provider=chain[0],
        resolve_tier_binding=lambda _tier: TierBinding(provider=None, model=None),
        build_provider_chain=lambda _primary: chain,
        fallback_provider_list=chain[1:],
        **{name: SimpleNamespace(get_api_key=lambda name=name: "key") for name in chain},
    )
    settings = SimpleNamespace(
        llm=llm,
        observability=SimpleNamespace(
            circuit_failures_to_open=circuit_failures_to_open,
            circuit_open_seconds=30.0,
        ),
        app=SimpleNamespace(environment="development"),
    )
    factory = LLMClientFactory(settings=settings)  # type: ignore[arg-type]
    factory.get_client = lambda provider_name=None: ports[provider_name or chain[0]]  # type: ignore[method-assign]
    return factory


def _client(factory: LLMClientFactory) -> Any:
    return factory.get_client_for_agent(
        AgentConfig(name="test_agent", role="critic", model_tier="mid"),
    )


@pytest.mark.asyncio()
async def test_capability_gap_does_not_open_the_breaker() -> None:
    """Repeated image calls must keep reaching the primary, not report an outage."""
    primary = _Port(VisionUnsupportedError("text-only"))
    secondary = _Port(VisionUnsupportedError("text-only"))
    factory = _factory_with_ports(
        {"openai": primary, "anthropic": secondary},
        circuit_failures_to_open=1,
    )
    client = _client(factory)

    for expected_calls in (1, 2, 3):
        with pytest.raises(VisionUnsupportedError):
            await client.generate(_messages())
        assert primary.calls == expected_calls, "vision refusal must not open the breaker"
        assert secondary.calls == 0, "an image call never fails over (ADR 0007)"


@pytest.mark.asyncio()
async def test_vision_call_never_falls_over_to_a_text_provider() -> None:
    """No fallback at all: a text provider would answer about an image it never saw."""
    factory = _factory_with_ports(
        {
            "openai": _Port(VisionUnsupportedError("text-only")),
            "anthropic": _Port(VisionUnsupportedError("text-only")),
        },
    )
    client = _client(factory)

    with pytest.raises(VisionUnsupportedError, match="text-only"):
        await client.generate(_messages())


@pytest.mark.asyncio()
async def test_outage_is_still_reported_as_outage_not_as_vision_gap() -> None:
    """A primary vision outage surfaces as the outage; no provider is tried next."""
    secondary = _Port(None)
    factory = _factory_with_ports(
        {"openai": _Port(RuntimeError("provider down")), "anthropic": secondary},
    )
    client = _client(factory)

    with pytest.raises(RuntimeError, match="provider down"):
        await client.generate(_messages())
    assert secondary.calls == 0


@pytest.mark.asyncio()
async def test_breakers_still_open_for_real_outages() -> None:
    """The vision exception path must not weaken the existing breaker behaviour."""
    factory = _factory_with_ports(
        {"openai": _Port(RuntimeError("provider down")), "anthropic": _Port(RuntimeError("provider down"))},
        circuit_failures_to_open=1,
    )
    client = _client(factory)
    text_only = [ChatMessage(role="user", content="hi")]

    with pytest.raises(RuntimeError, match="fallback chain failed"):
        await client.generate(text_only)
    with pytest.raises(CircuitOpenError):
        await client.generate(text_only)
