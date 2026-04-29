# Tools

## Principe général

Les capacités actionnables par le LLM sont exposées sous forme de tools enregistrés au chargement des modules. Le registre est simple, explicite, et sans framework externe.

## Enregistrement et exécution

Le contrat de base est:

```python
@register(name="tool_name", description="...", parameters={...})
def my_tool(arg1: str, _context: dict = None) -> str:
    ...
```

Règles à préserver:

- les tools sont importés pour effet de bord au démarrage;
- si un handler accepte `_context`, il reçoit au moins le `chat_id`;
- un handler synchrone est exécuté via `asyncio.to_thread`;
- les tools renvoient des chaînes, y compris pour les erreurs.

## Familles de tools

- shell: exécution de commandes système;
- fichiers: lecture, écriture, édition simple, listing;
- web: recherche et récupération de contenu;
- recherche déléguée: `web_research` — lance des sub-agents de recherche en parallèle (boucle isolée web_search/web_fetch/read_file), retourne une synthèse consolidée;
- market: `market_watch` — screener par stratégie (rebound / swing) sur une watchlist, alimenté par Degiro (close-only);
- degiro: `degiro_portfolio`, `degiro_search`, `degiro_quote`, `degiro_candles`, `degiro_indicators`, `degiro_chart` — lecture seule, aucune capacité de passer un ordre (méthodes `place_order`, `check_order`, `confirm_order`, `cancel_order` physiquement retirées du client vendored). `degiro_chart` produit un PNG via QuickChart.io et le pousse dans le chat Telegram en `send_photo`;
- home assistant: recherche d'entités exposées, lecture d'état et appel de services via Supervisor;
- reminders: création et gestion de rappels;
- routage: `escalate_model` pour la bascule de modèle.

`audio.py` n'est pas un tool: c'est une utilité interne de transcription pour Telegram.

## Exposition conditionnelle

- `web_search` n'est exposé que si `cfg.brave_api_key` est configurée.
- les tools de la famille `degiro_*` ne sont exposés que si `cfg.degiro_username` et `cfg.degiro_password` sont configurés. Le provider gère le login initial et le relogin auto via fingerprint HMAC-SHA256 (voir `veille-boursiere.md`).
- `market_watch` dépend du même prérequis Degiro, et lit la watchlist workspace `skills/market-watch/watchlist.json` (format ISIN-first).
- les tools Home Assistant ne sont exposés que si `cfg.supervisor_token` est configuré.
- les tools Home Assistant limitent l'accès aux entités portant le label `cfg.ha_expose_label`.
- `escalate_model` n'est exposé que tant que le run est encore sur le modèle léger.

## Limites et garde-fous actuels

- sortie shell tronquée à 10 000 caractères;
- lecture de fichier tronquée à 50 000 caractères;
- récupération web tronquée à 20 000 caractères.
- `web_research`: jusqu'à 5 sous-tâches par appel, max 3 sub-agents concurrents (semaphore), timeout 180 s par sub-agent. Voir `sub-agents.md`.
- cache de résolution du label Home Assistant: 60 secondes.
- veille boursière: indicateurs close-only (Degiro ne fournit ni volume ni OHL). Les confirmations volume ne sont pas disponibles — croiser avec `web_search` / `web_fetch` si nécessaire.
- `degiro_chart`: rendu via QuickChart.io (POST `/chart/create`, dépendance externe). Downsampling uniforme à ≤ 250 points (limite anonyme du service). Premier et dernier point préservés; perte ≤ 4 % sur `1y-1d` / `5y-1w`. Renvoie un message texte court; l'image arrive séparément en `send_photo` Telegram.
- famille `degiro_*`: lecture seule. Les méthodes de passage d'ordre ne sont pas importables (retirées du client vendored). Le portefeuille peut être lu, les analyses techniques proposées, mais aucun ordre ne peut être déclenché par l'agent.

Le projet ne sandboxe pas les tools à l'intérieur du conteneur. Cette liberté est intentionnelle et fait partie du contrat d'usage du projet.

## Visibilité côté utilisateur

Tous les tools ne sont pas visibles depuis Telegram. Les messages de progression utilisateur reposent sur un mapping court et lisible vers une petite sélection de tools lents ou significatifs.

## Quand documenter ici

Mettre à jour ce fichier dès qu'un changement touche:

- la liste des tools disponibles;
- leur mode d'exposition;
- leur forme de retour;
- leurs limites;
- leur visibilité ou leur effet perçu côté utilisateur.
- leur modèle de cache local ou leur consommation de quota externe.
