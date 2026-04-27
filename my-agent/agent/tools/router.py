"""Tool: escalate_model — signal the agent loop to switch to the full model."""

from agent.tools import register


@register(
    name="escalate_model",
    description=(
        "Escalate to the stronger model for this turn. Use for complex "
        "reasoning, synthesis, or planning that the lighter model "
        "struggles with. For web research, prefer web_research, which "
        "delegates to a sub-agent and keeps the main context clean. "
        "No parameters."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def escalate_model() -> str:
    return "OK — model escalated. Continue with your task."
