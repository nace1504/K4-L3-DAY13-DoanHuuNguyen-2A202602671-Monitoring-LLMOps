from __future__ import annotations

from app import agent as agent_module


class ManagedPrompt:
    version = 1

    def compile(self, **variables: str) -> str:
        return (
            f"Feature={variables['feature']}\n"
            f"Docs={variables['docs']}\n"
            f"Question={variables['message']}"
        )


class RecordingLangfuseClient:
    def __init__(self) -> None:
        self.prompt = ManagedPrompt()
        self.span_updates: list[dict] = []
        self.generation_updates: list[dict] = []

    def get_prompt(self, name: str, **kwargs):
        return self.prompt

    def update_current_span(self, **kwargs) -> None:
        self.span_updates.append(kwargs)

    def update_current_generation(self, **kwargs) -> None:
        self.generation_updates.append(kwargs)


def _run_agent(monkeypatch, message: str) -> tuple[agent_module.LabAgent, RecordingLangfuseClient]:
    monkeypatch.setenv("LANGFUSE_PROMPT_NAME", "day13-chat")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: True)

    agent = agent_module.LabAgent()
    agent_module.LabAgent.run.__wrapped__(
        agent,
        user_id="student-01",
        feature="qa",
        session_id="session-01",
        message=message,
        correlation_id="req-12345678",
    )
    return agent, client


def test_generation_receives_model_usage_cost_and_prompt(monkeypatch) -> None:
    agent, client = _run_agent(monkeypatch, "Explain the monitoring policy")

    assert len(client.generation_updates) == 1
    generation = client.generation_updates[0]
    assert generation["model"] == agent.model
    usage = generation["usage_details"]
    assert usage["input"] > 0
    assert usage["output"] > 0
    assert generation["cost_details"]["total"] == agent._estimate_cost(usage["input"], usage["output"])
    assert generation["prompt"] is client.prompt
    assert generation["metadata"]["ttft_ms"] >= 0


def test_generation_input_and_output_are_scrubbed(monkeypatch) -> None:
    # No retrieved docs keeps the question inside the 80-char preview, so the
    # assertion proves scrubbing rather than truncation removed the email.
    monkeypatch.setattr(agent_module, "retrieve", lambda message: [])
    _, client = _run_agent(monkeypatch, "Contact a@b.com")

    generation = client.generation_updates[0]
    assert "[REDACTED_EMAIL]" in str(generation["input"])
    assert "a@b.com" not in str(generation["input"])
    assert "a@b.com" not in str(generation["output"])
