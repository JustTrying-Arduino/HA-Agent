# Architecture globale

## Mission du projet

Le projet est un agent IA minimaliste distribué comme add-on Home Assistant. Il tourne dans un conteneur Docker Alpine, échange principalement via Telegram, expose un dashboard via ingress Home Assistant, et s'appuie sur l'API OpenAI avec une boucle maison de type `tool_use`.

## Vue d'ensemble

```text
Telegram (polling) -> Bot -> Agent Loop -> OpenAI API
                           |       |        |
                           |       |        +-> outils
                           |       |
                           |       +-> SQLite
                           |
                           +-> Scheduler rappels

Dashboard (aiohttp, ingress HA) -> SQLite
```

Le système tourne dans un seul process Python et un seul event loop `asyncio`. Le bot Telegram, le scheduler des rappels et le serveur web du dashboard partagent ce même runtime. Les handlers de tools synchrones sont déportés dans `asyncio.to_thread`.

## Composants et responsabilités

- `agent/main.py`: point d'entrée, initialisation des services, démarrage et arrêt propres.
- `agent/loop.py`: boucle agent, appels LLM, exécution des tools, collecte des tokens.
- `agent/prompt.py`: construction du prompt système à partir du workspace et du contexte récent.
- `agent/telegram.py`: réception des messages Telegram, placeholder, dispatch texte et audio.
- `agent/reminders.py` et `agent/scheduler.py`: stockage, calcul des prochaines échéances et exécution des rappels.
- `agent/server.py` et `agent/static/index.html`: dashboard et API JSON.
- `agent/db.py`: base SQLite, création des tables et configuration WAL.
- `agent/tools/`: registre et implémentations de tools.
- `agent/ha_client.py`: client Supervisor pour les interactions Home Assistant natives.

## Cycle de démarrage

Au démarrage, l'application:

1. configure le logging;
2. initialise la base SQLite;
3. importe les modules de tools pour les enregistrer;
4. démarre en parallèle le bot Telegram, le scheduler et le serveur web;
5. attend un signal d'arrêt pour fermer proprement les services.

## Flux structurants

- Message Telegram entrant -> sauvegarde du message -> construction du prompt -> appels LLM et tools -> sauvegarde de la réponse -> envoi au chat.
- Déclenchement d'un rappel -> création d'un message de contexte structuré -> run agent en mode `cron=True` -> éventuel envoi de message final.
- Lecture dashboard -> endpoints JSON -> agrégations SQLite -> rendu front côté navigateur.
- Appel Home Assistant natif -> client Supervisor -> API Core HA -> retour texte normalisé au LLM.

## Choix d'architecture à préserver

- Pas de framework agentique: la boucle reste explicite et simple à suivre.
- Le conteneur est la frontière de sécurité: pas de sandbox applicative interne pour les tools shell et fichiers.
- Le bot utilise le polling Telegram, pas les webhooks.
- La base de données est une SQLite unique avec WAL, suffisante pour un usage single-user.
- Le workspace vit dans `/share/myagent/workspace/`, persistant et éditable depuis Home Assistant.

## Configuration

Le flux de configuration suit cette chaîne:

`config.yaml` -> options Home Assistant -> `/data/options.json` -> `run.sh` -> variables d'environnement -> `Config.from_env()` -> singleton `cfg`.

## Logs et observabilité

Le niveau de log global est piloté par `cfg.log_level` (option add-on). La politique des niveaux est :

- **INFO** : événements métier observables en prod, une ligne par événement, faible volume. Toujours préfixés par `chat_id=X` quand un chat est concerné. Couvre : début et fin de run agent (`Agent run start` / `Agent run end` avec durée, nombre de tool calls et flag d'escalation), chaque appel et résultat de tool, escalation modèle, action Home Assistant effective (`HA service call`), login Degiro, message entrant et sortant Telegram, lifecycle du process.
- **DEBUG** : détail technique pour diagnostiquer un cas précis. Une seule ligne par fait, sans redondance entre une vue brute et une vue extraite. Couvre : payload complet d'une requête et d'une réponse LLM (chacun en une ligne tronquée à `DEBUG_TEXT_LIMIT`), payload d'un appel HA, requêtes et caches HA, traces de validation Degiro réussies.
- **WARNING** : erreurs récupérées qui dégradent silencieusement la qualité des résultats (ex. validation `price_history` ou `price_metadata` Degiro KO, `metadata fetch failed` côté market). Visibles en INFO sans monter à DEBUG.

Règles à préserver lors d'évolutions :

- pas de doublon entre INFO et DEBUG sur un même événement, DEBUG ajoute du contexte sur une ligne séparée et clairement nommée;
- toute action effective sur un système externe (HA, Degiro en écriture si un jour ouvert) reste en INFO;
- une erreur rattrapée silencieusement reste au minimum en WARNING.

## Hors périmètre actuel

Ces capacités ne sont pas implémentées à ce jour:

- streaming token par token dans Telegram;
- mode multi-agent;
- mode webhook pour Telegram.
