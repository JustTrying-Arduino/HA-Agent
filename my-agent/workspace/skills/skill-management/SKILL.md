# Skill Management

## Purpose
Help the agent decide when a reusable skill should be created or updated, and how to keep that skill focused, durable, and safe to reuse later.

## Use This Skill When
- The user explicitly asks to create, modify, save, or improve a skill.
- The user gives a complex multi-step procedure that should be reused in future sessions.
- The user asks the agent to remember operational instructions and apply them repeatedly.
- The user describes a recurring workflow that is better stored as a reusable procedure than as a one-off memory note.

## Instructions
- First decide whether the request belongs in a skill, `USER.md`, `MEMORY.md`, or a reminder.
- Use a skill for reusable procedures and standing instructions.
- Use `USER.md` for durable user-specific preferences or profile facts.
- Use `MEMORY.md` for durable non-user facts, project decisions, paths, or environment notes.
- Use reminders when the user wants the task executed at a specific time or on a schedule.
- Before creating a new skill, inspect the existing files in `/share/myagent/workspace/skills/` and read the closest relevant `SKILL.md` if one already exists.
- Prefer updating an existing skill when the new instructions extend or refine the same workflow.
- Create a new skill only when the workflow is meaningfully distinct and deserves its own trigger conditions.
- When creating a skill, make it narrow, action-oriented, and self-contained.
- Give the skill a clear name, a short purpose, explicit usage conditions, and concrete instructions.
- Avoid storing temporary tasks, timestamps, chat-specific context, or verbose logs inside a skill.
- If the user wants repeated execution on a schedule, store the reusable procedure in the skill and then create or update a reminder that invokes that workflow.
- After creating or updating a skill, briefly confirm what was stored and when it should be used.
