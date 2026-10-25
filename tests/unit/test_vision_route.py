"""Vision route: blob resolution, adapter payload, no-fallback, turn assembly (ADR 0007).

Three seams are pinned here, in the order the bytes travel:

* ``BlobVisionImageSource`` — storage-truth checks before anything is base64-encoded;
* ``LiteLLMAdapter`` — a resolved image becomes an OpenAI-compatible ``image_url``
  part on the *vision* alias, and an unresolved part is refused, not dropped;
* ``VisionImageService`` — attachment rows become approved parts under an owner scope,
  with PII / size / count denials carrying typed reasons.
"""

from __future__ import annotations

import base64

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from pydantic import SecretStr

from palatium_ai.application.services.vision_images import VisionImageService
from palatium_ai.core.config.llm.qwen import QwenLLMConfig
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.attachments.context import AttachmentContextBlock
from palatium_ai.domain.attachments.models import Attachment
from palatium_ai.domain.llm.errors import VisionImageUnavailableError, VisionUnsupportedError
from palatium_ai.domain.llm.models import ChatMessage, ImagePart
from palatium_ai.domain.ports.blob_store import BlobStat
from palatium_ai.infrastructure.llm.litellm_adapter import LiteLLMAdapter
from palatium_ai.infrastructure.vision.blob_image_source import BlobVisionImageSource

_MAX_BYTES = 10 * 1024 * 1024
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _part(attachment_id: UUID | None = None, mime: str = "image/png") -> ImagePart:
    return ImagePart(attachment_id=attachment_id or uuid4(), mime=mime)  # type: ignore[arg-type]


class _BlobStore:
    """Minimal in-memory ``BlobStorePort`` double: stat/read report the given facts."""

    def __init__(self, *, data: bytes | None = None, content_type: str | None = "image/png") -> None:
        self._data = data
        self._content_type = content_type
        self.reads = 0

    async def presigned_put_url(self, key: str, *, content_type: str, expires_seconds: int) -> str:
        raise NotImplementedError

    async def presigned_get_url(self, key: str, *, expires_seconds: int) -> str:
        raise NotImplementedError

    async def stat(self, key: str) -> BlobStat | None:
        if self._data is None:
            return None
        return BlobStat(key=key, size_bytes=len(self._data), content_type=self._content_type)

    async def read_bytes(self, key: str) -> bytes:
        self.reads += 1
        if self._data is None:
            raise FileNotFoundError(key)
        return self._data

    async def write_bytes(self, key: str, data: bytes, *, content_type: str) -> None:
        self._data = data
        self._content_type = content_type

    async def exists(self, key: str) -> bool:
        return self._data is not None

    async def delete(self, key: str) -> None:  # pragma: no cover - unused in tests
        _ = key


# --- blob source --------------------------------------------------------------


@pytest.mark.asyncio()
async def test_source_returns_stored_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pillow may be absent in a bare test image; the decode budget has its own tests.
    monkeypatch.setattr(
        "palatium_ai.infrastructure.vision.blob_image_source.assert_image_decode_within_budget",
        lambda _data: None,
    )
    source = BlobVisionImageSource(_BlobStore(data=_PNG_BYTES), max_image_bytes=_MAX_BYTES)
    assert await source.read(uuid4(), expected_mime="image/png") == _PNG_BYTES


@pytest.mark.asyncio()
async def test_source_refuses_a_missing_blob() -> None:
    source = BlobVisionImageSource(_BlobStore(data=None), max_image_bytes=_MAX_BYTES)
    with pytest.raises(VisionImageUnavailableError, match="missing"):
        await source.read(uuid4(), expected_mime="image/png")


@pytest.mark.asyncio()
async def test_source_refuses_a_media_type_the_store_never_saw() -> None:
    """A part that claims PNG while the store holds a PDF is tampering, not a hint."""
    source = BlobVisionImageSource(
        _BlobStore(data=_PNG_BYTES, content_type="application/pdf"),
        max_image_bytes=_MAX_BYTES,
    )
    with pytest.raises(VisionImageUnavailableError, match="does not match"):
        await source.read(uuid4(), expected_mime="image/png")


@pytest.mark.asyncio()
async def test_source_refuses_an_oversized_payload_before_reading_again() -> None:
    store = _BlobStore(data=_PNG_BYTES)
    source = BlobVisionImageSource(store, max_image_bytes=len(_PNG_BYTES) - 1)
    with pytest.raises(VisionImageUnavailableError, match="byte cap"):
        await source.read(uuid4(), expected_mime="image/png")
    assert store.reads == 0, "the cap must be enforced on stat, not after a full read"


# --- adapter ------------------------------------------------------------------


def _qwen_config() -> QwenLLMConfig:
    return QwenLLMConfig(
        api_key=SecretStr("test-key"),
        base_url="http://127.0.0.1:9/v1",
        default_model="text-model",
    )


class _ImageSource:
    def __init__(self, data: bytes = _PNG_BYTES) -> None:
        self._data = data

    async def read(self, attachment_id: UUID, *, expected_mime: str) -> bytes:
        _ = attachment_id, expected_mime
        return self._data


@pytest.mark.asyncio()
async def test_adapter_sends_the_vision_alias_and_a_data_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def _ok(**kwargs: Any) -> object:
        captured.update(kwargs)
        return _completion()

    monkeypatch.setattr("palatium_ai.infrastructure.llm.litellm_adapter.acompletion", _ok)
    adapter = LiteLLMAdapter(
        _qwen_config(),
        vision_model="vision-tier",
        image_source=_ImageSource(),
    )
    await adapter.generate([ChatMessage(role="user", content="what is here?", image_parts=(_part(),))])

    assert "vision-tier" in str(captured["model"]), "the text model must not be used for images"
    content = captured["messages"][0]["content"]
    assert isinstance(content, list)
    image = content[1]
    assert image["type"] == "image_url"
    url = image["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == _PNG_BYTES


@pytest.mark.asyncio()
async def test_adapter_refuses_images_without_a_configured_alias() -> None:
    adapter = LiteLLMAdapter(_qwen_config(), image_source=_ImageSource())
    with pytest.raises(VisionUnsupportedError, match="LLM_VISION_MODEL"):
        await adapter.generate([ChatMessage(role="user", content="hi", image_parts=(_part(),))])


@pytest.mark.asyncio()
async def test_adapter_refuses_images_without_a_source(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok(**kwargs: Any) -> object:  # pragma: no cover - must not be called
        raise AssertionError(kwargs)

    monkeypatch.setattr("palatium_ai.infrastructure.llm.litellm_adapter.acompletion", _ok)
    adapter = LiteLLMAdapter(_qwen_config(), vision_model="vision-tier")
    with pytest.raises(VisionUnsupportedError, match="source is not wired"):
        await adapter.generate([ChatMessage(role="user", content="hi", image_parts=(_part(),))])


@pytest.mark.asyncio()
async def test_text_call_keeps_the_agent_model(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def _ok(**kwargs: Any) -> object:
        captured.update(kwargs)
        return _completion()

    monkeypatch.setattr("palatium_ai.infrastructure.llm.litellm_adapter.acompletion", _ok)
    adapter = LiteLLMAdapter(
        _qwen_config(),
        vision_model="vision-tier",
        image_source=_ImageSource(),
    )
    await adapter.generate([ChatMessage(role="user", content="hi")], model="tier-small")
    assert "tier-small" in str(captured["model"])
    assert captured["messages"] == [{"role": "user", "content": "hi"}]


def _completion() -> object:
    from types import SimpleNamespace

    message = SimpleNamespace(content="ok")
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=None,
        model="vision-tier",
    )


# --- turn assembly ------------------------------------------------------------


def _attachment(
    *,
    user_id: str = "user-1",
    mime_type: str = "image/png",
    contains_pii: bool = False,
    size_bytes: int = len(_PNG_BYTES),
) -> Attachment:
    return Attachment(
        id=uuid4(),
        user_id=user_id,
        thread_id="thread-1",
        filename="chart.png",
        mime_type=mime_type,
        size_bytes=size_bytes,
        blob_key=f"attachments/{uuid4()}",
        mode="attach",
        status="ready",
        contains_pii=contains_pii,
        created_at=datetime.now(UTC),
    )


def _service(
    *, data: bytes | None = _PNG_BYTES, content_type: str | None = "image/png", max_images: int = 4
) -> VisionImageService:
    return VisionImageService(
        _BlobStore(data=data, content_type=content_type),
        vision_model="vision-tier",
        max_image_bytes=_MAX_BYTES,
        max_images=max_images,
    )


@pytest.mark.asyncio()
async def test_service_allows_a_clean_image() -> None:
    attachment = _attachment()
    outcome = await _service().images_for([attachment], user_id="user-1")
    assert [part.attachment_id for part in outcome.parts] == [attachment.id]
    assert outcome.denials == ()
    assert outcome.has_images is True


@pytest.mark.asyncio()
async def test_service_denies_pii_images() -> None:
    outcome = await _service().images_for([_attachment(contains_pii=True)], user_id="user-1")
    assert outcome.parts == ()
    assert [denial.reason for denial in outcome.denials] == ["pii_blocked"]


@pytest.mark.asyncio()
async def test_service_denies_missing_blobs() -> None:
    outcome = await _service(data=None).images_for([_attachment()], user_id="user-1")
    assert [denial.reason for denial in outcome.denials] == ["image_missing"]


@pytest.mark.asyncio()
async def test_service_skips_non_images_silently() -> None:
    outcome = await _service(content_type="application/pdf").images_for(
        [_attachment(mime_type="application/pdf")],
        user_id="user-1",
    )
    assert outcome.parts == ()
    assert outcome.denials == ()


@pytest.mark.asyncio()
async def test_service_caps_the_image_count() -> None:
    outcome = await _service(max_images=1).images_for(
        [_attachment(), _attachment()],
        user_id="user-1",
    )
    assert len(outcome.parts) == 1
    assert [denial.reason for denial in outcome.denials] == ["too_many_images"]


@pytest.mark.asyncio()
async def test_service_refuses_a_foreign_row() -> None:
    with pytest.raises(ValueError, match="does not belong"):
        await _service().images_for([_attachment(user_id="user-2")], user_id="user-1")


@pytest.mark.asyncio()
async def test_service_without_alias_denies_every_image() -> None:
    service = VisionImageService(
        _BlobStore(data=_PNG_BYTES),
        vision_model=None,
        max_image_bytes=_MAX_BYTES,
        max_images=4,
    )
    outcome = await service.images_for([_attachment()], user_id="user-1")
    assert [denial.reason for denial in outcome.denials] == ["vision_not_configured"]


# --- PII opt-in (ALLOW_PII_IMAGES) --------------------------------------------


@pytest.mark.asyncio()
async def test_pii_image_travels_only_with_the_owner_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default stays fail-closed; the flag forwards, audits and counts the exception."""
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        "palatium_ai.application.services.vision_images.add_span_event",
        lambda name, attributes=None: events.append((name, attributes or {})),
    )
    service = VisionImageService(
        _BlobStore(data=_PNG_BYTES),
        vision_model="vision-tier",
        max_image_bytes=_MAX_BYTES,
        max_images=4,
        allow_pii_images=True,
    )
    attachment = _attachment(contains_pii=True)

    outcome = await service.images_for([attachment], user_id="user-1")

    assert [part.attachment_id for part in outcome.parts] == [attachment.id]
    assert outcome.denials == ()
    assert events, "a forwarded PII image must emit an auditable span event"
    assert events[0][0] == "gen_ai.pii_image_allowed"
    assert events[0][1]["attachment_id"] == str(attachment.id)
    assert agent_metrics.vision_image_count(outcome="allowed", reason="pii_allowed") >= 1


@pytest.mark.asyncio()
async def test_the_flag_does_not_disable_any_other_gate() -> None:
    """PII opt-in is not a bypass: size and the alias still decide before it."""
    service = VisionImageService(
        _BlobStore(data=_PNG_BYTES),
        vision_model="vision-tier",
        max_image_bytes=len(_PNG_BYTES) - 1,
        max_images=4,
        allow_pii_images=True,
    )
    outcome = await service.images_for([_attachment(contains_pii=True)], user_id="user-1")
    assert outcome.parts == ()
    assert [denial.reason for denial in outcome.denials] == ["image_too_large"]


# --- turn blocks (graph delivery channel) --------------------------------------


def _block(
    *,
    mime_type: str = "image/png",
    contains_pii: bool = False,
    attachment_id: UUID | None = None,
) -> AttachmentContextBlock:
    return AttachmentContextBlock(
        attachment_id=attachment_id or uuid4(),
        filename="chart.png",
        source="attachment:chart.png",
        fenced_text="<<<UNTRUSTED>>>…",
        action="allow",
        mime_type=mime_type,
        contains_pii=contains_pii,
    )


@pytest.mark.asyncio()
async def test_blocks_become_parts_for_the_turn() -> None:
    block = _block()
    outcome = await _service().parts_for_blocks([block])
    assert [part.attachment_id for part in outcome.parts] == [block.attachment_id]


@pytest.mark.asyncio()
async def test_block_admission_reuses_the_row_pii_flag() -> None:
    outcome = await _service().parts_for_blocks([_block(contains_pii=True)])
    assert outcome.parts == ()
    assert [denial.reason for denial in outcome.denials] == ["pii_blocked"]


@pytest.mark.asyncio()
async def test_block_admission_skips_documents() -> None:
    outcome = await _service().parts_for_blocks([_block(mime_type="application/pdf")])
    assert outcome.parts == ()
    assert outcome.denials == ()


@pytest.mark.asyncio()
async def test_block_admission_denies_a_vanished_blob() -> None:
    outcome = await _service(data=None).parts_for_blocks([_block()])
    assert [denial.reason for denial in outcome.denials] == ["image_missing"]
