"""Tools: file operations (read, write, edit, list)."""

import os
from agent.tools import register

MAX_READ = 50000


@register(
    name="read_file",
    description="Read the content of a file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file"},
        },
        "required": ["path"],
    },
)
def read_file(path: str) -> str:
    content = open(path).read()
    if len(content) > MAX_READ:
        return content[:MAX_READ] + "\n... (truncated)"
    return content


@register(
    name="write_file",
    description="Write content to a file (creates or overwrites).",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    },
)
def write_file(path: str, content: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return f"Written {len(content)} bytes to {path}"


@register(
    name="edit_file",
    description="Edit a file by replacing the first occurrence of old_text with new_text.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the file"},
            "old_text": {"type": "string", "description": "Text to find"},
            "new_text": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_text", "new_text"],
    },
)
def edit_file(path: str, old_text: str, new_text: str) -> str:
    content = open(path).read()
    if old_text not in content:
        return f"Error: old_text not found in {path}"
    new_content = content.replace(old_text, new_text, 1)
    with open(path, "w") as f:
        f.write(new_content)
    return f"Edited {path} successfully"


@register(
    name="list_dir",
    description="List files and directories at the given path.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path to the directory"},
        },
        "required": ["path"],
    },
)
def list_dir(path: str) -> str:
    entries = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        prefix = "d " if os.path.isdir(full) else "f "
        entries.append(prefix + name)
    return "\n".join(entries) if entries else "(empty directory)"
