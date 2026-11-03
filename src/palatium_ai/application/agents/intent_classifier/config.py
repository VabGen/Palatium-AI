# src/palatium_ai/application/agents/intent_classifier/config.py

"""IntentClassifier AgentConfig (030)."""

from palatium_ai.domain.agents.agent_config import AgentConfig

#: The classifier answers with a small JSON envelope (axes + short reasoning), so its
#: output budget stays far below a generative default. Passing it to ``call_llm`` also
#: shrinks the dynamic per-call timeout, which is linear in ``max_tokens`` (055).
INTENT_CLASSIFIER_MAX_OUTPUT_TOKENS = 512

INTENT_CLASSIFIER_CONFIG = AgentConfig(
    name="intent_classifier",
    role="intent_classifier",
    model_tier="small",
    temperature=0.0,
    allowed_tools=(),
    # Intent gates every hop: it must answer inside the turn's 15 s budget, not the
    # 60 s it used to inherit. One attempt only — a retry spends the whole turn waiting
    # for a label the graph can already route around (a failed classification degrades
    # to the default answer path, 055). 10 s is enough for a ~300-token JSON envelope.
    timeout_seconds=20,
    llm_call_timeout_seconds=10.0,
    max_retries=1,
    confidence_threshold=0.7,
)
