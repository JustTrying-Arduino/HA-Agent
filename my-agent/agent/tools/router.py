"""Tool: escalate_model — signal the agent loop to switch to the full model."""

from agent.tools import register


@register(
    name="escalate_model",
    description=(
        "Escalate to the more powerful LLM model for the rest of this turn. "
        "Call this BEFORE answering when the task requires advanced reasoning, "
        "complex multi-step planning, nuanced writing, or when you are not "
        "confident in your ability to answer correctly. No parameters needed."
    ),
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def escalate_model() -> str:
    return "OK — model escalated. Continue with your task."
