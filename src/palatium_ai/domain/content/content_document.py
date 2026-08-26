# src/palatium_ai/domain/content/content_document.py

"""Typed user-facing content document (structured UI contract, no markdown fallback)."""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

IconToken = Literal[
    "calendar",
    "mail",
    "search",
    "document",
    "warning",
    "success",
    "danger",
    "info",
    "user",
    "users",
    "clock",
    "chart",
    "shield",
    "check",
    "x",
    "link",
    "edit",
    "settings",
]

CalloutTone = Literal["info", "success", "warning", "danger"]
ListStyle = Literal["ordered", "unordered"]
ChartKind = Literal["bar", "line", "pie"]
StepStatus = Literal["pending", "active", "done", "blocked"]
ActionKind = Literal["approve", "reject", "confirm", "dismiss", "custom"]
ActionStyle = Literal["primary", "secondary", "danger"]
HeadingLevel = Literal[1, 2, 3]
# How the document expects human participation (server turns this into HITL cards).
DocumentInteraction = Literal["none", "choice", "confirm"]
# Opaque widget id for UI registry — not a product allow-list.
_WIDGET_KIND_PATTERN = r"^[a-z][a-z0-9_]{0,62}$"


class HeadingBlock(BaseModel):
    """Section title."""

    model_config = {"frozen": True}

    type: Literal["heading"] = "heading"
    level: HeadingLevel = 2
    text: str = Field(min_length=1, max_length=500)
    icon: IconToken | None = None


class ParagraphBlock(BaseModel):
    """Body paragraph (plain text; UI applies typography)."""

    model_config = {"frozen": True}

    type: Literal["paragraph"] = "paragraph"
    text: str = Field(min_length=1, max_length=8000)


class ListItem(BaseModel):
    """Single list row."""

    model_config = {"frozen": True}

    text: str = Field(min_length=1, max_length=2000)
    icon: IconToken | None = None
    emphasis: str | None = Field(default=None, max_length=200)


class ListBlock(BaseModel):
    """Ordered or unordered list."""

    model_config = {"frozen": True}

    type: Literal["list"] = "list"
    style: ListStyle = "unordered"
    items: tuple[ListItem, ...] = Field(min_length=1)


class TableBlock(BaseModel):
    """Tabular data; row cell count must match columns (validated below)."""

    model_config = {"frozen": True}

    type: Literal["table"] = "table"
    columns: tuple[str, ...] = Field(min_length=1, max_length=20)
    rows: tuple[tuple[str, ...], ...] = Field(min_length=1)


class CalloutBlock(BaseModel):
    """Highlighted notice."""

    model_config = {"frozen": True}

    type: Literal["callout"] = "callout"
    tone: CalloutTone = "info"
    title: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    icon: IconToken | None = None


class CodeBlock(BaseModel):
    """Code fence for client syntax highlighting."""

    model_config = {"frozen": True}

    type: Literal["code"] = "code"
    language: str = Field(default="text", min_length=1, max_length=40)
    content: str = Field(min_length=1, max_length=50_000)


class FormulaBlock(BaseModel):
    """Math formula (KaTeX / MathJax on client)."""

    model_config = {"frozen": True}

    type: Literal["formula"] = "formula"
    latex: str = Field(min_length=1, max_length=4000)


class KeyValueItem(BaseModel):
    """Label/value pair."""

    model_config = {"frozen": True}

    label: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=2000)
    icon: IconToken | None = None


class KeyValueBlock(BaseModel):
    """Definition / metadata panel."""

    model_config = {"frozen": True}

    type: Literal["kv"] = "kv"
    items: tuple[KeyValueItem, ...] = Field(min_length=1)


class StepItem(BaseModel):
    """One step in a process timeline."""

    model_config = {"frozen": True}

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)
    status: StepStatus = "pending"
    icon: IconToken | None = None


class StepsBlock(BaseModel):
    """Multi-step process."""

    model_config = {"frozen": True}

    type: Literal["steps"] = "steps"
    items: tuple[StepItem, ...] = Field(min_length=1)


class ChartSeries(BaseModel):
    """Named numeric series for charts."""

    model_config = {"frozen": True}

    name: str = Field(min_length=1, max_length=100)
    values: tuple[float, ...] = Field(min_length=1)


class ChartBlock(BaseModel):
    """Typed chart spec — client renders; no image blobs."""

    model_config = {"frozen": True}

    type: Literal["chart"] = "chart"
    kind: ChartKind = "bar"
    labels: tuple[str, ...] = Field(min_length=1)
    series: tuple[ChartSeries, ...] = Field(min_length=1)
    title: str | None = Field(default=None, max_length=200)


class DividerBlock(BaseModel):
    """Visual separator."""

    model_config = {"frozen": True}

    type: Literal["divider"] = "divider"


class WidgetBlock(BaseModel):
    """Opaque external embed; UI/adapters resolve `kind`, core does not hardcode products."""

    model_config = {"frozen": True}

    type: Literal["widget"] = "widget"
    kind: str = Field(min_length=1, max_length=64, pattern=_WIDGET_KIND_PATTERN)
    ref_id: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=200)
    href: str | None = Field(default=None, max_length=2000)

    @field_validator("href")
    @classmethod
    def _http_https_href(cls, value: str | None) -> str | None:
        """Reject javascript:/data:/relative URLs — only absolute http(s)."""
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        parsed = urlparse(stripped)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("widget href must be an absolute http(s) URL")
        return stripped


ContentBlock = Annotated[
    HeadingBlock
    | ParagraphBlock
    | ListBlock
    | TableBlock
    | CalloutBlock
    | CodeBlock
    | FormulaBlock
    | KeyValueBlock
    | StepsBlock
    | ChartBlock
    | DividerBlock
    | WidgetBlock,
    Field(discriminator="type"),
]


class ActionSpec(BaseModel):
    """Clickable action / HITL choice (rendered as a card in UI)."""

    model_config = {"frozen": True}

    action_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    kind: ActionKind = "custom"
    style: ActionStyle = "secondary"
    icon: IconToken | None = None
    requires_confirmation: bool = False
    risk_score: float = Field(default=0.0, ge=0.0, le=1.0)


class DocumentMeta(BaseModel):
    """Non-visual metadata for clients and audit."""

    model_config = {"frozen": True}

    confidence: float = Field(ge=0.0, le=1.0)
    requires_review: bool = False
    source_refs: tuple[str, ...] = ()
    # none = informational; choice/confirm → server mints clickable HITL cards from actions.
    interaction: DocumentInteraction = "none"


class ContentDocument(BaseModel):
    """Canonical user-facing answer — structured blocks only."""

    model_config = {"frozen": True}

    schema_version: Literal[1] = 1
    locale: str = Field(min_length=2, max_length=16, pattern=r"^[a-z]{2}(-[A-Z]{2})?$")
    title: str | None = Field(default=None, max_length=300)
    blocks: tuple[ContentBlock, ...] = Field(min_length=1)
    actions: tuple[ActionSpec, ...] = ()
    meta: DocumentMeta

    def preview_text(self, limit: int = 200) -> str:
        """Short plain preview for session lists (derived, not a fallback channel)."""
        if self.title:
            return self.title[:limit]
        for block in self.blocks:
            if isinstance(block, HeadingBlock | ParagraphBlock):
                return block.text[:limit]
            if isinstance(block, CalloutBlock):
                return (block.title or block.body)[:limit]
            if isinstance(block, ListBlock) and block.items:
                return block.items[0].text[:limit]
            if isinstance(block, StepsBlock) and block.items:
                return block.items[0].title[:limit]
        return self.blocks[0].type[:limit]

    def plain_text(self, limit: int = 4000) -> str:
        """Flatten blocks for dialog transcript / Contextualizer (not UI)."""
        parts: list[str] = []
        if self.title:
            parts.append(self.title)
        for block in self.blocks:
            parts.extend(_block_plain_lines(block))
        text = "\n".join(part for part in parts if part.strip())
        if not text:
            return self.title or "(empty)"
        if len(text) > limit:
            return f"{text[: limit - 1]}…"
        return text


def _block_plain_lines(block: ContentBlock) -> list[str]:
    """Convert one content block into plain transcript lines."""
    match block:
        case HeadingBlock(text=text) | ParagraphBlock(text=text):
            return [text]
        case CalloutBlock(title=title, body=body):
            return [*([title] if title else []), body]
        case CodeBlock(content=content):
            return [content]
        case FormulaBlock(latex=latex):
            return [latex]
        case WidgetBlock(title=title, kind=kind):
            return [title or kind]
        case DividerBlock():
            return []
        case _:
            return _structured_block_plain_lines(block)


def _structured_block_plain_lines(block: ContentBlock) -> list[str]:
    """Flatten list/table/steps/kv/chart blocks."""
    match block:
        case ListBlock(items=items):
            return [f"• {item.text}" for item in items]
        case StepsBlock(items=items):
            return [f"• {item.title} — {item.body}" for item in items]
        case KeyValueBlock(items=items):
            return [f"{item.label}: {item.value}" for item in items]
        case TableBlock(columns=columns, rows=rows):
            return [" | ".join(columns), *(" | ".join(row) for row in rows)]
        case ChartBlock(title=title, labels=labels):
            return [f"{title or 'chart'}: {', '.join(labels)}"]
        case _:
            return []


def parse_content_document(payload: object) -> ContentDocument:
    """Validate arbitrary JSON-compatible payload into ContentDocument."""
    document = ContentDocument.model_validate(payload)
    _validate_table_shapes(document)
    _validate_chart_shapes(document)
    return document


def _validate_table_shapes(document: ContentDocument) -> None:
    for block in document.blocks:
        if not isinstance(block, TableBlock):
            continue
        width = len(block.columns)
        for row in block.rows:
            if len(row) != width:
                raise ValueError(f"table row length {len(row)} != columns length {width}")


def _validate_chart_shapes(document: ContentDocument) -> None:
    for block in document.blocks:
        if not isinstance(block, ChartBlock):
            continue
        n = len(block.labels)
        for series in block.series:
            if len(series.values) != n:
                raise ValueError(f"chart series '{series.name}' length {len(series.values)} != labels {n}")
