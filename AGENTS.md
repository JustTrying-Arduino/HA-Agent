# CLAUDE.md

## Mission du projet

HA-Agent est un agent IA minimaliste distribue comme add-on Home Assistant. Il fonctionne dans un conteneur Docker Alpine, dialogue surtout via Telegram, execute des actions via des tools, et expose un dashboard via ingress Home Assistant. Le projet repose sur le SDK OpenAI et une boucle `tool_use` maison, sans framework agentique.

## Resume architecture

```text
Telegram (polling) -> Bot -> Agent Loop -> OpenAI API
                           |        |
                           |        +-> tools
                           |
                           +-> SQLite <- Dashboard
                           |
                           +-> Scheduler rappels
```

Le runtime est un process Python unique avec un seul event loop `asyncio`. Le bot Telegram, le scheduler et le serveur web y cohabitent.

## Regles globales

### Conventions techniques

- Python 3.12+ autorise, avec typage moderne.
- Async par defaut. Les handlers de tools synchrones passent par `asyncio.to_thread`.
- `cfg` dans `agent/config.py` est la source unique de configuration runtime.
- Les timestamps sont stockes en UTC ISO 8601. L'heure locale sert au prompt et aux affichages.
- Les skills ne sont pas injectees entierement dans le prompt: seul un index compact est expose, et le detail se lit a la demande via `read_file`.

### Add-on Home Assistant

- Image de base: `ghcr.io/home-assistant/{arch}-base:3.22`.
- `run.sh` lit `/data/options.json` avec `jq`, puis exporte les variables d'environnement.
- `init: false` dans `my-agent/config.yaml`.
- Commande d'entree: `python3 -m agent.main`.
- Toute livraison GitHub doit inclure un bump de `version` dans `my-agent/config.yaml`.

### Documentation

- `AGENTS.md` est le hub de contribution: regles globales, conventions et index documentaire.
- La documentation fonctionnelle detaillee vit dans `docs/fonctionnel/`.
- Toute evolution fonctionnelle doit mettre a jour, dans le meme changement, le ou les fichiers concernes dans `docs/fonctionnel/`, ainsi que leur index si le perimetre documentaire change.
- Si une evolution touche plusieurs themes, mettre a jour tous les fichiers impactes, pas seulement le plus proche.
- En cas de doute, documenter. Une documentation stale est consideree comme un bug.

## Index documentation fonctionnelle

Consulter les fichiers suivants selon la zone modifiee:
- [`docs/fonctionnel/README.md`](./docs/fonctionnel/README.md): point d'entree, perimetre des fichiers et regles de maintenance croisee.
- [`docs/fonctionnel/architecture-globale.md`](./docs/fonctionnel/architecture-globale.md): vue d'ensemble, composants, flux et choix structurants.
- [`docs/fonctionnel/agent-loop-et-prompt.md`](./docs/fonctionnel/agent-loop-et-prompt.md): boucle agent, prompt, sessions, historique recent.
- [`docs/fonctionnel/routage-modele.md`](./docs/fonctionnel/routage-modele.md): escalation vers le modele principal et observabilite associee.
- [`docs/fonctionnel/telegram.md`](./docs/fonctionnel/telegram.md): UX Telegram, placeholder, reponses, audio.
- [`docs/fonctionnel/multi-chat.md`](./docs/fonctionnel/multi-chat.md): isolation par `chat_id`, contexte par conversation et vues dashboard multi-chat.
- [`docs/fonctionnel/dashboard.md`](./docs/fonctionnel/dashboard.md): endpoints, comportements du dashboard et front.
- [`docs/fonctionnel/homeassistant.md`](./docs/fonctionnel/homeassistant.md): integration Supervisor, tools HA natifs, filtrage par label et config associee.
- [`docs/fonctionnel/reminders.md`](./docs/fonctionnel/reminders.md): rappels, scheduler, declenchements cron.
- [`docs/fonctionnel/tools.md`](./docs/fonctionnel/tools.md): enregistrement, exposition, limites et effets visibles des tools.
- [`docs/fonctionnel/workspace-et-memoire.md`](./docs/fonctionnel/workspace-et-memoire.md): workspace persistant, skills, memoire durable.

## coding rules
### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.
