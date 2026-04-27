# CLAUDE.md

## Projet

HA-Agent est un agent IA minimaliste distribue comme add-on Home Assistant. Il tourne dans un conteneur Docker Alpine, interagit surtout via Telegram, execute des actions via des tools, et expose un dashboard via ingress Home Assistant.

Le projet repose sur le SDK OpenAI et une boucle `tool_use` maison, sans framework agentique.

## Architecture

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

## Regles de contribution

### 1. Clarifier avant de coder

- Ne pas supposer silencieusement.
- Expliciter les hypotheses importantes.
- Si plusieurs interpretations sont possibles, les nommer.
- Si quelque chose est ambigu ou contradictoire, s'arreter et demander.

### 2. Garder le code simple

- Ecrire le minimum necessaire pour resoudre le besoin.
- Ne pas ajouter de flexibilite, d'abstraction ou de configuration non demandee.
- Ne pas couvrir des cas impossibles.
- Si une solution parait trop lourde, la simplifier.

### 3. Faire des changements chirurgicaux

- Ne modifier que ce qui sert directement la demande.
- Ne pas refactorer le code adjacent sans besoin explicite.
- Conserver le style existant du projet.
- Supprimer uniquement les imports, variables ou fonctions rendus inutiles par tes propres changements.
- Signaler le code mort preexistant au lieu de le supprimer d'office.

Test mental: chaque ligne modifiee doit se relier directement a la demande utilisateur.

## Conventions techniques

- Python 3.12+ avec typage moderne.
- Async par defaut. Les handlers synchrones passent par `asyncio.to_thread`.
- `cfg` dans `agent/config.py` est la source unique de configuration runtime.
- Les timestamps sont stockes en UTC ISO 8601. L'heure locale sert au prompt et aux affichages.
- Les skills ne sont pas injectees entierement dans le prompt: seul un index compact est expose, et le detail se lit a la demande via `read_file`.

## Contraintes Add-on Home Assistant

- Image de base: `ghcr.io/home-assistant/{arch}-base:3.22`
- `run.sh` lit `/data/options.json` avec `jq`, puis exporte les variables d'environnement
- `init: false` dans `my-agent/config.yaml`
- Commande d'entree: `python3 -m agent.main`
- Toute livraison GitHub doit inclure un bump de `version` dans `my-agent/config.yaml`

## Documentation

`CLAUDE.md` sert de hub de contribution. La documentation fonctionnelle detaillee vit dans `docs/fonctionnel/`.

Regles:
- `CLAUDE.md` et `AGENTS.md` doivent rester alignes. Toute modification de fond de l'un doit etre repercutee dans l'autre, hors differences de nom de fichier si necessaire.
- Toute evolution fonctionnelle doit mettre a jour, dans le meme changement, les fichiers `docs/fonctionnel/` concernes.
- Si plusieurs themes sont touches, mettre a jour tous les fichiers impactes.
- Si le perimetre documentaire change, mettre aussi a jour l'index.
- En cas de doute, documenter. Une documentation stale est consideree comme un bug.

## Index documentation fonctionnelle

- [`docs/fonctionnel/README.md`](./docs/fonctionnel/README.md): point d'entree et regles de maintenance croisee
- [`docs/fonctionnel/architecture-globale.md`](./docs/fonctionnel/architecture-globale.md): vue d'ensemble, composants et flux
- [`docs/fonctionnel/agent-loop-et-prompt.md`](./docs/fonctionnel/agent-loop-et-prompt.md): boucle agent, prompt, sessions, historique recent
- [`docs/fonctionnel/routage-modele.md`](./docs/fonctionnel/routage-modele.md): escalation vers le modele principal et observabilite
- [`docs/fonctionnel/telegram.md`](./docs/fonctionnel/telegram.md): UX Telegram, placeholders, reponses, audio
- [`docs/fonctionnel/multi-chat.md`](./docs/fonctionnel/multi-chat.md): isolation par `chat_id` et vues multi-chat
- [`docs/fonctionnel/dashboard.md`](./docs/fonctionnel/dashboard.md): endpoints et comportements du dashboard
- [`docs/fonctionnel/homeassistant.md`](./docs/fonctionnel/homeassistant.md): integration Supervisor, tools HA, filtrage par label
- [`docs/fonctionnel/reminders.md`](./docs/fonctionnel/reminders.md): rappels, scheduler, cron
- [`docs/fonctionnel/tools.md`](./docs/fonctionnel/tools.md): enregistrement, exposition, limites et effets visibles des tools
- [`docs/fonctionnel/sub-agents.md`](./docs/fonctionnel/sub-agents.md): boucles LLM imbriquees (sub-agents), `web_research`, contexte isole
- [`docs/fonctionnel/veille-boursiere.md`](./docs/fonctionnel/veille-boursiere.md): veille boursiere via Degiro (close-only), cache local, watchlist ISIN-first, strategies rebond / swing
- [`docs/fonctionnel/portefeuille.md`](./docs/fonctionnel/portefeuille.md): lecture portefeuille Degiro, skill `portfolio-advisor`, regle "jamais d'ordre", limitations close-only
- [`docs/fonctionnel/workspace-et-memoire.md`](./docs/fonctionnel/workspace-et-memoire.md): workspace persistant, skills, memoire durable
