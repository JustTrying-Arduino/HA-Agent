# Dashboard

## Rôle

Le dashboard expose une vue d'audit et de suivi de l'agent depuis Home Assistant ingress. Il lit les données SQLite via une API JSON servie par `aiohttp`.

## Endpoints fonctionnels

- `/api/stats?period=day|week|month`: agrégats de tokens et estimations de coût.
- `/api/messages?chat_id=X&limit=50`: historique des messages et tool calls associés.
- `/api/tool_calls?limit=50`: audit des appels d'outils.
- `/api/reminders?status=active|all`: liste des rappels.

## Comportement front

Le front est volontairement simple:

- un seul fichier HTML avec JavaScript natif;
- pas de framework, pas de build step, pas de `node_modules`;
- URLs API relatives pour rester compatibles avec l'ingress Home Assistant.

## Comportements UI notables

- en-tête et barre d'onglets sticky;
- affichage des dates au format `dd/mm HH:MM`;
- table des tool calls compacte avec détail extensible;
- badge de modèle sur les réponses assistant quand l'information est disponible;
- lecture des coûts tenant compte des cached tokens.

## Développement local

Le front sait tomber sur des mocks intégrés si l'API n'est pas joignable en local. Ce fallback sert uniquement à faciliter le développement front hors backend et ne doit pas modifier le comportement en production.

## Points d'attention

- Toute évolution d'un endpoint doit être répercutée dans le front et dans cette documentation.
- Toute donnée ajoutée au dashboard doit préciser son origine en base ou dans la boucle agent.
