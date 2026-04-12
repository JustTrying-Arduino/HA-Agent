"""Home Assistant tools exposed through the Supervisor API."""

from agent.config import cfg

if cfg.supervisor_token:
    from agent.ha_client import get_client
    from agent.tools import register


    def _friendly_name(state: dict) -> str:
        return str(state.get("attributes", {}).get("friendly_name") or "-")


    def _state_summary(state: dict) -> str:
        attrs = state.get("attributes", {}) or {}
        value = str(state.get("state", "unknown"))
        unit = attrs.get("unit_of_measurement")
        if unit:
            value = f"{value} {unit}"
        return value


    def _state_line(state: dict) -> str:
        return f"{state.get('entity_id', '?')} | {_friendly_name(state)} | {_state_summary(state)}"


    @register(
        name="ha_search_entities",
        description=(
            "Search Home Assistant entities exposed to the agent through the configured label. "
            "Use this before reading or controlling an entity when you are not certain of the exact entity_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional case-insensitive substring to match against entity_id and friendly name.",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional Home Assistant domain like light, switch, climate, cover, or sensor.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return. Defaults to 20.",
                    "minimum": 1,
                    "maximum": 100,
                },
            },
        },
    )
    async def ha_search_entities(
        query: str | None = None,
        domain: str | None = None,
        limit: int = 20,
    ) -> str:
        limit = max(1, min(int(limit), 100))
        client = get_client()
        allowed_entities = set(await client.get_labeled_entities())
        if not allowed_entities:
            return "No entities exposed."

        states = await client.get_states()
        results = [state for state in states if state.get("entity_id") in allowed_entities]

        if domain:
            prefix = f"{domain.lower()}."
            results = [state for state in results if str(state.get("entity_id", "")).lower().startswith(prefix)]

        if query:
            needle = query.lower()
            results = [
                state for state in results
                if needle in str(state.get("entity_id", "")).lower()
                or needle in _friendly_name(state).lower()
            ]

        if not results:
            return "No matching entities found."

        results.sort(key=lambda state: str(state.get("entity_id", "")))
        return "\n".join(_state_line(state) for state in results[:limit])


    @register(
        name="ha_get_state",
        description=(
            "Read the current state and attributes of a Home Assistant entity that is exposed to the agent label."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "Exact Home Assistant entity_id, for example light.living_room.",
                },
            },
            "required": ["entity_id"],
        },
    )
    async def ha_get_state(entity_id: str) -> str:
        client = get_client()
        if not await client.entity_allowed(entity_id):
            return f"Error: entity '{entity_id}' is not exposed to the agent."

        state = await client.get_state(entity_id)
        attrs = state.get("attributes", {}) or {}
        lines = [
            f"entity_id: {state.get('entity_id', entity_id)}",
            f"state: {state.get('state', 'unknown')}",
            f"last_changed: {state.get('last_changed', 'unknown')}",
            "attributes:",
        ]
        if attrs:
            for key in sorted(attrs):
                lines.append(f"- {key}: {attrs[key]}")
        else:
            lines.append("- (none)")
        return "\n".join(lines)


    @register(
        name="ha_call_service",
        description=(
            "Call a Home Assistant service on an exposed entity. "
            "Use only a real entity_id returned by ha_search_entities or confirmed by the user."
        ),
        parameters={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Service domain like light, switch, climate, cover, or script.",
                },
                "service": {
                    "type": "string",
                    "description": "Service name like turn_on, turn_off, toggle, open_cover, or set_temperature.",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Exact Home Assistant entity_id that must be exposed to the agent.",
                },
                "service_data": {
                    "type": "object",
                    "description": "Optional extra JSON object to merge into the service payload.",
                },
            },
            "required": ["domain", "service", "entity_id"],
        },
    )
    async def ha_call_service(
        domain: str,
        service: str,
        entity_id: str,
        service_data: dict | None = None,
    ) -> str:
        client = get_client()
        if not await client.entity_allowed(entity_id):
            return f"Error: entity '{entity_id}' is not exposed to the agent."

        payload = {"entity_id": entity_id}
        if service_data:
            payload.update(service_data)

        result = await client.call_service(domain, service, payload)

        if isinstance(result, list) and result:
            lines = [f"Service called: {domain}.{service} on {entity_id}"]
            lines.extend(_state_line(state) for state in result if isinstance(state, dict))
            if len(lines) > 1:
                return "\n".join(lines)

        return f"Service called: {domain}.{service} on {entity_id}"
