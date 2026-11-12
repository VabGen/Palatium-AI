"""W10.1 P0.1 — instructional StepsBlock must not become formatter_output_invalid."""

from __future__ import annotations

from palatium_ai.domain.content import (
    ContentDocument,
    DocumentMeta,
    ListBlock,
    ListItem,
    StepItem,
    StepsBlock,
)
from palatium_ai.domain.hitl.interaction_policy import HitlInteractionPolicy


def test_w101_instructional_steps_are_not_formatter_output_invalid() -> None:
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title=None,
        blocks=(
            StepsBlock(
                type="steps",
                items=(
                    StepItem(
                        title="Проверка существующих ключей",
                        body="Откройте терминал и выполните `ls -al ~/.ssh`.",
                        status="done",
                        icon="check",
                    ),
                    StepItem(
                        title="Генерация нового SSH-ключа",
                        body='Выполните `ssh-keygen -t ed25519 -C "you@example.com"`.',
                        status="pending",
                        icon="edit",
                    ),
                    StepItem(
                        title="Добавление ключа в ssh-agent",
                        body="Запустите agent и `ssh-add`.",
                        status="pending",
                        icon="link",
                    ),
                    StepItem(
                        title="Копирование публичного ключа",
                        body="`cat ~/.ssh/id_ed25519.pub`",
                        status="pending",
                        icon="document",
                    ),
                    StepItem(
                        title="Добавление ключа в GitHub",
                        body="Settings → SSH and GPG keys → New SSH key.",
                        status="pending",
                        icon="check",
                    ),
                    StepItem(
                        title="Проверка подключения",
                        body="`ssh -T git@github.com`",
                        status="pending",
                        icon="check",
                    ),
                ),
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=1.0, requires_review=False, source_refs=(), interaction="none"),
    )
    plan = HitlInteractionPolicy.plan(doc, requires_review=False, task_kind="knowledge_request")
    assert plan.reason != "formatter_output_invalid"
    assert plan.required_choice is False
    assert plan.choice_actions == ()
    assert plan.menu_shaped is False
    assert plan.promoted_from == "none"


def test_w101_list_menus_still_promote() -> None:
    """Exclusive pickers remain ListBlock-shaped (steps are never menus)."""
    doc = ContentDocument(
        schema_version=1,
        locale="en-US",
        title="Pick analysis",
        blocks=(
            ListBlock(
                type="list",
                style="ordered",
                items=(
                    ListItem(text="Content Analysis", icon=None, emphasis=None),
                    ListItem(text="Risk Analysis", icon=None, emphasis=None),
                    ListItem(text="Compliance Analysis", icon=None, emphasis=None),
                ),
            ),
        ),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=(), interaction="none"),
    )
    plan = HitlInteractionPolicy.plan(doc, requires_review=False)
    assert plan.menu_shaped is True
    assert len(plan.choice_actions) == 3
    assert plan.reason != "formatter_output_invalid"
