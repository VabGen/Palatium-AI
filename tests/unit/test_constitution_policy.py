"""Answer constitution (S2): deterministic articles, closed ids, no value in details."""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.critic.prompts import CRITIC_SYSTEM_PROMPT
from palatium_ai.domain.policies.constitution import Constitution

_SECRET = "sk-abc123456789012345"
_EMAIL = "ivan.petrov@example.com"


def test_articles_have_unique_ids_and_text() -> None:
    articles = Constitution.articles()

    assert len({article.id for article in articles}) == len(articles)
    assert all(article.statement.strip() for article in articles)


def test_every_article_is_announced_to_the_judge() -> None:
    """Drift gate: the prompt is assembled from the policy, so no article can vanish."""
    for article in Constitution.articles():
        assert article.id in CRITIC_SYSTEM_PROMPT


def test_empty_draft_is_never_a_violation() -> None:
    assert Constitution.check(draft=None) == ()
    assert Constitution.check(draft="   ") == ()


def test_secret_echo_is_high_severity() -> None:
    violations = Constitution.check(draft=f"ваш ключ {_SECRET}")

    assert [violation.principle for violation in violations] == ["no_secret_echo"]
    assert violations[0].severity == "high"
    assert _SECRET not in violations[0].detail


def test_pii_quoted_from_this_turns_input_is_legitimate() -> None:
    draft = f"Вы указали {_EMAIL} — отправим туда."
    assert Constitution.check(draft=draft, sources=(f"мой адрес {_EMAIL}",)) == ()


def test_pii_from_no_input_is_flagged() -> None:
    violations = Constitution.check(draft=f"Контакт: {_EMAIL}", sources=("другой текст",))

    assert [violation.principle for violation in violations] == ["no_pii_echo_without_permission"]
    assert violations[0].severity == "medium"
    assert violations[0].detail == "email"
    assert _EMAIL not in violations[0].detail


def test_pii_quoted_from_evidence_is_legitimate() -> None:
    draft = "В договоре указан счёт BY12ABCD1234567890."
    evidence = "Реквизиты: BY12ABCD1234567890"

    assert Constitution.check(draft=draft, sources=(evidence,)) == ()


@pytest.mark.parametrize(
    "draft",
    (
        "Secret: " + _SECRET,
        "Ключ sk-abc123456789012345 и токен",
    ),
)
def test_secret_is_flagged_wherever_it_sits(draft: str) -> None:
    assert any(v.principle == "no_secret_echo" for v in Constitution.check(draft=draft))


def test_clean_draft_has_no_violations() -> None:
    assert Constitution.check(draft="Договор подписан 12 марта.", sources=("Договор подписан",)) == ()
