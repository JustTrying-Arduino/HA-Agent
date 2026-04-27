# Sub-agents

## Principe

Un sub-agent est une boucle LLM imbriquée déclenchée par un tool de l'agent principal. Il a son propre contexte (jetable), un prompt système court, et un set d'outils restreint. Seule la synthèse finale produite par le sub-agent remonte à l'agent principal.

Objectif : préserver le contexte de l'agent principal des résultats verbeux des recherches web (5 résultats Brave + plusieurs pages fetch jusqu'à 20 KB chacune), tout en parallélisant plusieurs angles de recherche.

L'implémentation actuelle est **synchrone** : pendant l'exécution du tool, l'agent principal attend la fin de toutes les sous-tâches.

## `web_research`

Tool unique exposé à l'agent principal. Prend une liste de tâches (1 à 5) et lance un sub-agent par tâche en parallèle.

### Schéma

```json
{
  "tasks": [
    {"question": "<question autonome>", "hint": "<contexte optionnel>"}
  ]
}
```

### Sub-agent loop

Implémenté dans `agent/subagent.py`. Caractéristiques :

- même modèle léger que l'agent principal (`cfg.openai_model_light`);
- prompt système court : rôle, contraintes (`<= 4 web_search`, `<= 5 web_fetch`, sortie `<= 1500` caractères, sources listées en bas);
- toolset restreint à `{web_search, web_fetch, read_file}`;
- timeout 180 s par sub-agent;
- ni `save_message`, ni `expire_session_if_needed`, ni `progress_callback` — état isolé.

La concurrence est limitée à 3 sub-agents simultanés via un `asyncio.Semaphore` côté tool.

### Format de retour à l'agent principal

```
## <question 1>
<synthèse 1>

## <question 2>
<synthèse 2>
```

En cas d'échec d'un sub-agent : `[ERREUR] <message>` à la place de la synthèse, l'agent principal décide quoi en faire.

## Observabilité

Les tokens consommés par chaque sub-agent sont loggés dans la table `token_usage` au nom du `parent_chat_id` avec un model taggé `subagent:<model>` (par exemple `subagent:gpt-4.1-mini`). Cela permet de séparer la conso sub-agent de celle de l'agent principal sans changer le schéma DB.

Les tool calls effectués par le sub-agent (`web_search`, `web_fetch`, `read_file`) passent par le registry standard et sont donc journalisés dans `tool_calls` au nom du `parent_chat_id`.

## Limites et garde-fous

- Maximum 5 tâches par appel (limité au schéma JSON).
- Maximum 3 sub-agents concurrents (semaphore au niveau du tool).
- Pas de récursion : `web_research` n'est pas dans le toolset des sub-agents.
- Timeout 180 s par sub-agent ; au-delà, on retourne ce qui a été produit.
- Pas de retry automatique sur échec.
- Le `LOOP_TIMEOUT` de 300 s de l'agent principal reste actif : un batch trop long peut couper la boucle parente.

## Quand documenter ici

Mettre à jour ce fichier dès qu'un changement touche :

- la liste des sub-agents ou des tools les exposant;
- leur prompt système ou leur toolset;
- les limites de concurrence ou de timeout;
- le format de retour à l'agent principal;
- le mode (synchrone vs futur asynchrone).
