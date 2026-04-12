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

### Documentation

- `CLAUDE.md` est le hub de contribution: regles globales, conventions et index documentaire.
- La documentation fonctionnelle detaillee vit dans `docs/fonctionnel/`.
- Toute evolution fonctionnelle doit mettre a jour, dans le meme changement, le ou les fichiers concernes dans `docs/fonctionnel/`, ainsi que leur index si le perimetre documentaire change.
- Si une evolution touche plusieurs themes, mettre a jour tous les fichiers impactes, pas seulement le plus proche.
- En cas de doute, documenter. Une documentation stale est consideree comme un bug.

### Conventions techniques

- Python 3.12+ autorise, avec typage moderne.
- Async par defaut. Les handlers de tools synchrones passent par `asyncio.to_thread`.
- `cfg` dans `agent/config.py` est la source unique de configuration runtime.
- Les timestamps sont stockes en UTC ISO 8601. L'heure locale sert au prompt et aux affichages.
- Le projet reste sans framework agentique et sans build frontend.

### Add-on Home Assistant

- Image de base: `ghcr.io/home-assistant/{arch}-base:3.22`.
- `run.sh` lit `/data/options.json` avec `jq`, puis exporte les variables d'environnement.
- `init: false` dans `my-agent/config.yaml`.
- Commande d'entree: `python3 -m agent.main`.
- Toute livraison GitHub doit inclure un bump de `version` dans `my-agent/config.yaml`.

## Index documentation fonctionnelle

Consulter les fichiers suivants selon la zone modifiee:

- [`docs/fonctionnel/README.md`](./docs/fonctionnel/README.md): point d'entree, perimetre des fichiers et regles de maintenance croisee.
- [`docs/fonctionnel/architecture-globale.md`](./docs/fonctionnel/architecture-globale.md): vue d'ensemble, composants, flux et choix structurants.
- [`docs/fonctionnel/agent-loop-et-prompt.md`](./docs/fonctionnel/agent-loop-et-prompt.md): boucle agent, prompt, sessions, historique recent.
- [`docs/fonctionnel/routage-modele.md`](./docs/fonctionnel/routage-modele.md): escalation vers le modele principal et observabilite associee.
- [`docs/fonctionnel/telegram.md`](./docs/fonctionnel/telegram.md): UX Telegram, placeholder, reponses, audio.
- [`docs/fonctionnel/dashboard.md`](./docs/fonctionnel/dashboard.md): endpoints, comportements du dashboard et front.
- [`docs/fonctionnel/homeassistant.md`](./docs/fonctionnel/homeassistant.md): integration Supervisor, tools HA natifs, filtrage par label et config associee.
- [`docs/fonctionnel/reminders.md`](./docs/fonctionnel/reminders.md): rappels, scheduler, declenchements cron.
- [`docs/fonctionnel/tools.md`](./docs/fonctionnel/tools.md): enregistrement, exposition, limites et effets visibles des tools.
- [`docs/fonctionnel/workspace-et-memoire.md`](./docs/fonctionnel/workspace-et-memoire.md): workspace persistant, skills, memoire durable.

## Guide rapide

| Changement | A verifier |
|------------|------------|
| Nouveau tool ou modification d'un tool | `docs/fonctionnel/tools.md` |
| Evolution de la boucle agent ou du prompt | `docs/fonctionnel/agent-loop-et-prompt.md` |
| Changement de logique de routage LLM | `docs/fonctionnel/routage-modele.md` |
| Changement visible dans Telegram | `docs/fonctionnel/telegram.md` |
| Changement dashboard ou API web | `docs/fonctionnel/dashboard.md` |
| Changement integration Home Assistant native | `docs/fonctionnel/homeassistant.md` |
| Changement rappels ou scheduler | `docs/fonctionnel/reminders.md` |
| Changement workspace, skills ou memoire | `docs/fonctionnel/workspace-et-memoire.md` |
