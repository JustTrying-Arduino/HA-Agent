# My Agent — Home Assistant Add-on

Agent IA minimaliste qui tourne dans Home Assistant. Il communique via Telegram, peut exécuter des commandes, manipuler des fichiers, chercher sur le web, et transcrire des messages vocaux. Un dashboard intégré permet de suivre la consommation de tokens et l'historique des échanges.

## Architecture

```
Telegram ──► Bot (polling) ──► Boucle Agent ──► OpenAI API
                                    │
                            ┌───────┼───────┐
                            ▼       ▼       ▼
                          exec   files    web
                          shell  r/w/edit search/fetch
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

Tout le workspace (prompts, skills, cron, mémoire) et la base SQLite vivent dans `/share/myagent/`. Ce dossier est persistent entre les redémarrages et accessible via File Editor, Samba, et SSH dans Home Assistant.

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

### Cron via crond Alpine

Les tâches planifiées sont des fichiers JSON dans `workspace/cron/`. Au démarrage, `run.sh` génère le crontab. Chaque cron lance un process Python séparé qui exécute l'agent avec un prompt additionnel (`Prompt_Cron.md`).

**Pourquoi** : crond est déjà dans Alpine, fiable, et ne consomme rien. Le process séparé évite la complexité d'injecter des messages dans le bot running.

## Installation

1. Ajouter ce dépôt comme add-on local dans Home Assistant
2. Installer l'add-on "My Agent"
3. Configurer les options :
   - `openai_api_key` (obligatoire)
   - `telegram_bot_token` (obligatoire — créer via [@BotFather](https://t.me/BotFather))
   - `telegram_allowed_chat_ids` (obligatoire — votre chat ID Telegram)
   - `groq_api_key` (optionnel — pour les messages vocaux)
   - `brave_api_key` (optionnel — pour la recherche web)
4. Démarrer l'add-on

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
| `Prompt_Cron.md` | Instructions additionnelles pour les tâches cron |
| `skills/` | Dossiers de skills (chacun avec un `SKILL.md`) |
| `cron/*.json` | Tâches planifiées |

Tous ces fichiers sont éditables directement depuis File Editor dans HA.

### Format cron

```json
{
    "schedule": "0 8 * * *",
    "message": "Donne-moi un résumé météo pour aujourd'hui.",
    "channel": "telegram"
}
```

Le champ `schedule` suit la syntaxe crontab standard. Renommer le fichier sans `.disabled` pour l'activer, puis redémarrer l'add-on.

## Tools disponibles

| Tool | Description |
|------|-------------|
| `exec` | Exécuter une commande shell (timeout 30s) |
| `read_file` | Lire un fichier |
| `write_file` | Créer ou écraser un fichier |
| `edit_file` | Modifier un fichier (recherche/remplacement) |
| `list_dir` | Lister un répertoire |
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
| Cron | crond Alpine |
| Image de base | ghcr.io/home-assistant/{arch}-base:3.22 |
