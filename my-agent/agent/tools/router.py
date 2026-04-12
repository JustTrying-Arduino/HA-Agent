"""Tool: escalate_model — signal the agent loop to switch to the full model."""

from agent.tools import register


@register(
    name="escalate_model",
    description=(
        "Escalate to the stronger model for this turn. Use before any "
        "web search/browsing or tasks likely to need 2+ tool calls. "
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
