# My Agent — Home Assistant Add-on

Agent IA minimaliste qui tourne dans Home Assistant. Il communique via Telegram, peut exécuter des commandes, manipuler des fichiers, chercher sur le web, et transcrire des messages vocaux. Un dashboard intégré permet de suivre la consommation de tokens et l'historique des échanges.

## Architecture

```
Telegram ──► Bot (polling) ──► Boucle Agent ──► OpenAI API
                                    │
                            ┌───────┼────────┬──────────┐
                            ▼       ▼        ▼          ▼
                          exec   files      web     reminders
                          shell  r/w/edit  fetch     scheduler
                                                    + storage
                                                      │
                                                SQLite ◄──── Dashboard (ingress HA)
```

L'agent tourne dans un seul container Docker Alpine (~60-80 MB). Tout est dans un process Python unique : le bot Telegram (polling), la boucle agent, et le serveur web dashboard partagent le même event loop asyncio.

## Parti-pris techniques

### Pas de framework agentique

Pas de LangChain, CrewAI, ou autre. La boucle agent est un simple `while` sur les `tool_calls` de l'API OpenAI (~80 lignes dans `loop.py`). Le registre de tools est un décorateur `@register` qui mappe un nom vers un handler + un schéma JSON. C'est tout.

**Pourquoi** : moins de dépendances, moins de magie, plus facile à débugger. Le SDK OpenAI fait déjà tout le travail.

### Accès libre dans le container

Pas de sandboxing des commandes shell ou des chemins de fichiers. Le tool `exec` fait un `subprocess.run(cmd, shell=True)` sans restriction. Le container Docker **est** l'isolation.

**Pourquoi** : l'agent doit pouvoir tout faire dans son environnement — installer des paquets, modifier des configs, lancer des scripts. La frontière de sécurité est le container, pas l'agent.

### Stockage dans /share

Tout le workspace (prompts, skills, mémoire) et la base SQLite vivent dans `/share/myagent/`. Ce dossier est persistent entre les redémarrages et accessible via File Editor, Samba, et SSH dans Home Assistant.

**Pourquoi** : l'utilisateur peut éditer les prompts et les skills directement depuis HA, sans rebuild du container.

### Polling Telegram (pas webhook)

Le bot utilise `start_polling()` au lieu de webhooks.

**Pourquoi** : pas besoin d'exposer un port ou de configurer un reverse proxy. Fonctionne derrière un NAT sans aucune config réseau.

### SQLite unique

Une seule base SQLite avec 3 tables (messages, token_usage, tool_calls). Pas de Redis, pas de PostgreSQL.

**Pourquoi** : suffisant pour un agent single-user. WAL mode pour la lecture concurrente entre le bot et le dashboard. La base fait quelques Mo même après des mois d'utilisation.

### Dashboard vanilla JS

Le dashboard est un fichier HTML unique (~250 lignes) sans framework, sans build step, sans node_modules.

**Pourquoi** : le dashboard affiche 3 vues simples (tokens, messages, tool calls). React ou Vue serait du over-engineering. Le fichier est servi tel quel par aiohttp.

### Cached tokens trackés séparément

Les tokens en cache (prompt caching OpenAI) sont comptés à part dans la base et affichés dans le dashboard. Le calcul de coût applique un tarif réduit (~75% moins cher) aux cached tokens.

**Pourquoi** : sur des conversations longues avec le même prompt système, le caching peut réduire les coûts de 50%+. Visible dans le dashboard pour comprendre ses dépenses réelles.

### Sessions : fenêtre glissante + timeout

- **Timeout 48h** : si le dernier message date de plus de 48h, la session est archivée et on repart à zéro
- **Fenêtre 15 messages** : seuls les 15 derniers messages sont envoyés au LLM

Les messages archivés restent consultables dans le dashboard.

**Pourquoi** : compromis entre contexte utile et consommation de tokens. 15 messages couvrent une conversation typique. Le timeout évite d'envoyer du contexte obsolète.

### Mémoire long-terme via fichier

L'agent écrit lui-même dans `MEMORY.md` quand on lui demande de retenir quelque chose. Ce fichier est injecté dans le prompt système à chaque requête.

**Pourquoi** : pas de vector database, pas d'embeddings. Un fichier Markdown est lisible, éditable par l'utilisateur, et suffisant pour un agent personnel.

### Rappels natifs via scheduler interne

Les rappels ponctuels et récurrents sont stockés en SQLite et pilotés par un scheduler interne. L'agent peut créer, lister, modifier et annuler ses propres rappels via des tools dédiés. Lorsqu'un rappel se déclenche, l'agent est relancé avec un prompt additionnel dédié (`Prompt_Reminder.md`).

**Pourquoi** : activation immédiate sans redémarrage, gestion correcte des rappels one-shot, historique et archivage, et suppression de toute dépendance à `crond` ou à des fichiers JSON manuels.

## Installation

1. Dans Home Assistant, aller dans **Paramètres → Modules complémentaires → Boutique des modules complémentaires**
2. Menu ⋮ en haut à droite → **Dépôts** → ajouter l'URL : `https://github.com/JustTrying-Arduino/HA-Agent`
3. Rafraîchir la page, chercher "My Agent" et l'installer
4. Configurer les options :
   - `openai_api_key` (obligatoire)
   - `telegram_bot_token` (obligatoire — créer via [@BotFather](https://t.me/BotFather))
   - `telegram_allowed_chat_ids` (obligatoire — votre chat ID Telegram)
   - `groq_api_key` (optionnel — pour les messages vocaux)
   - `brave_api_key` (optionnel — pour la recherche web)
5. Démarrer l'add-on

Le dashboard est accessible via le panneau latéral de l'add-on dans HA.

## Configuration

| Option | Défaut | Description |
|--------|--------|-------------|
| `openai_api_key` | — | Clé API OpenAI (ou compatible : OpenRouter, LiteLLM) |
| `openai_api_base` | `https://api.openai.com/v1` | URL de base de l'API |
| `openai_model` | `gpt-4.1` | Modèle à utiliser |
| `groq_api_key` | — | Clé API Groq pour Whisper (transcription vocale) |
| `brave_api_key` | — | Clé API Brave Search |
| `telegram_bot_token` | — | Token du bot Telegram |
| `telegram_allowed_chat_ids` | `[]` | Chat IDs autorisés |
| `session_timeout_hours` | `48` | Timeout de session en heures |
| `max_session_messages` | `15` | Nombre max de messages en contexte |
| `log_level` | `info` | Niveau de log (debug, info, warning, error) |

## Workspace

Les fichiers du workspace sont dans `/share/myagent/workspace/` :

| Fichier | Rôle |
|---------|------|
| `AGENT.md` | Prompt système — identité, règles, comportement |
| `USER.md` | Profil utilisateur |
| `MEMORY.md` | Mémoire long-terme (écrit par l'agent) |
| `Prompt_Reminder.md` | Instructions additionnelles pour les déclenchements planifiés |
| `skills/` | Dossiers de skills (chacun avec un `SKILL.md`) |

Tous ces fichiers sont éditables directement depuis File Editor dans HA.

## Tools disponibles

| Tool | Description |
|------|-------------|
| `exec` | Exécuter une commande shell (timeout 30s) |
| `read_file` | Lire un fichier |
| `write_file` | Créer ou écraser un fichier |
| `edit_file` | Modifier un fichier (recherche/remplacement) |
| `list_dir` | Lister un répertoire |
| `create_reminder` | Créer un rappel ponctuel ou récurrent |
| `list_reminders` | Lister les rappels du chat courant |
| `update_reminder` | Modifier un rappel existant |
| `cancel_reminder` | Annuler un rappel existant |
| `web_search` | Recherche Brave Search (si clé configurée) |
| `web_fetch` | Récupérer le contenu texte d'une URL |

## Stack technique

| Composant | Choix |
|-----------|-------|
| Langage | Python 3 |
| LLM | API OpenAI (SDK natif) |
| Speech-to-Text | Groq Whisper API |
| Recherche web | Brave Search API |
| Bot | python-telegram-bot (polling) |
| Dashboard | aiohttp + vanilla JS |
| Base de données | SQLite (WAL) |
| Scheduling | Scheduler interne + SQLite |
| Image de base | ghcr.io/home-assistant/{arch}-base:3.22 |

## Documentation interne

La documentation de maintenance du projet est volontairement séparée du guide utilisateur:

- [`CLAUDE.md`](./CLAUDE.md) : point d'entrée pour contribuer, avec règles globales et index documentaire
- [`docs/fonctionnel/README.md`](./docs/fonctionnel/README.md) : documentation fonctionnelle thématique pour les IA et développeurs
