# Home Assistant

## Purpose
Help the agent inspect and control Home Assistant entities through the native HA tools while respecting the configured exposure label.

## Use This Skill When
- The user asks what Home Assistant entities are available.
- The user wants the current state of a Home Assistant entity.
- The user wants to control a Home Assistant entity such as a light, switch, cover, climate device, scene, or script.

## Workflow
- Start with `ha_search_entities` whenever the exact `entity_id` is unknown or uncertain.
- Use `ha_get_state` before acting when the current state or attributes matter to the decision.
- Use `ha_call_service` only after you have a real exposed `entity_id`.

## Rules
- Never invent an `entity_id`.
- If several entities look plausible, ask the user to clarify which one they mean.
- Stay concise and action-oriented in your final answer.
- If the tool says an entity is not exposed, explain that it must be tagged with the configured Home Assistant label before you can access it.

## Common Services
- Lights: `light.turn_on`, `light.turn_off`, `light.toggle`
- Switches: `switch.turn_on`, `switch.turn_off`, `switch.toggle`
- Covers: `cover.open_cover`, `cover.close_cover`, `cover.stop_cover`
- Climate: `climate.set_temperature`, `climate.set_hvac_mode`, `climate.turn_on`, `climate.turn_off`
- Scenes and scripts: `scene.turn_on`, `script.turn_on`

## Good Defaults
- Prefer `ha_search_entities` over guessing.
- Prefer reading state before changing climate or cover devices.
- When using `ha_call_service`, include only the service data that is clearly required.
