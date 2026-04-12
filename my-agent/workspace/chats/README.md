# Chat-specific Context

Create one file per Telegram conversation in this folder.

## Naming
- Use the exact Telegram `chat_id` as the filename.
- Example: `123456789.md`
- Group chats often use a negative ID, for example `-1001234567890.md`

## Behavior
- The matching file is injected automatically into the system prompt for that chat only.
- Files are read on every message, so edits apply immediately.
- If a file does not exist, no chat-specific context is injected.

## Recommendations
- Keep each file short, durable, and specific to that conversation.
- Good examples: tone, shared routines, relationship context, recurring preferences, topics to prioritize.
- Avoid temporary tasks or one-off instructions better handled in the chat itself.
