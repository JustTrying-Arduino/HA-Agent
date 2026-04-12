# Home Assistant

## Rôle

Le projet peut exposer une famille de tools Home Assistant natifs quand il tourne comme add-on HA avec `SUPERVISOR_TOKEN` disponible.

## Exposition

- Les tools HA ne sont enregistrés que si `cfg.supervisor_token` est non vide.
- L'exposition des entités ne passe pas par une liste statique dans la config de l'add-on.
- La source de vérité est un label Home Assistant, `agent` par défaut, configurable via `ha_expose_label`.

## Client Supervisor

- Le client HTTP utilise `http://supervisor/core/api` avec authentification Bearer via `SUPERVISOR_TOKEN`.
- La session `aiohttp` est réutilisée pendant la vie du process.
- Le timeout total des requêtes est de 15 secondes.
- La résolution du label passe par `POST /api/template` avec `label_entities(...) | list`.
- La liste des entités exposées est mise en cache 60 secondes. Les lectures d'état et appels de service restent live.

## Tools disponibles

- `ha_search_entities`: liste les entités exposées, filtrables par domaine et requête textuelle.
- `ha_get_state`: lit l'état complet d'une entité exposée.
- `ha_call_service`: appelle un service HA sur une entité exposée.

## Garde-fous

- Une entité hors label est refusée avant lecture détaillée ou appel de service.
- Si aucune entité n'est exposée pour le label configuré, la recherche retourne `No entities exposed.`.
- Les erreurs HTTP sont normalisées en messages lisibles, notamment `Entity not found: <entity_id>` pour les 404 d'entité.

## Expérience agent

- Une skill workspace `home-assistant` guide le LLM vers le flux `ha_search_entities` -> `ha_get_state` -> `ha_call_service`.
- Telegram peut afficher des libellés de progression dédiés pendant les appels HA visibles.
