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
- market: veille boursière EOD via Marketstack avec cache SQLite local;
- home assistant: recherche d'entités exposées, lecture d'état et appel de services via Supervisor;
- reminders: création et gestion de rappels;
- routage: `escalate_model` pour la bascule de modèle.

`audio.py` n'est pas un tool: c'est une utilité interne de transcription pour Telegram.

## Exposition conditionnelle

- `web_search` n'est exposé que si `cfg.brave_api_key` est configurée.
- `market_watch` dépend d'une clé `cfg.marketstack_api_key` côté exécution pour pouvoir rafraîchir les données EOD.
- les tools Home Assistant ne sont exposés que si `cfg.supervisor_token` est configuré.
- les tools Home Assistant limitent l'accès aux entités portant le label `cfg.ha_expose_label`.
- `escalate_model` n'est exposé que tant que le run est encore sur le modèle léger.

## Limites et garde-fous actuels

- sortie shell tronquée à 10 000 caractères;
- lecture de fichier tronquée à 50 000 caractères;
- récupération web tronquée à 20 000 caractères.
- cache de résolution du label Home Assistant: 60 secondes.
- veille boursière bornée à des heuristiques EOD simples et à une watchlist workspace explicitement configurée.

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
