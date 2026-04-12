# Reminders

## Rôle

Les rappels permettent à l'agent de programmer des exécutions futures ponctuelles ou récurrentes, sans dépendre d'un service externe ni de `crond`.

## Stockage et planification

- Les rappels vivent dans la table SQLite `reminders`.
- Le scheduler inspecte les rappels dus toutes les 15 secondes.
- Deux formats de planification sont supportés:
  - `once`: date-heure ISO;
  - `recurring`: expression cron à 5 champs.

## Déclenchement

Quand un rappel arrive à échéance, le scheduler reconstruit un message de contexte structuré contenant au minimum:

- l'identifiant du rappel;
- son titre;
- son type;
- l'instruction à exécuter.

Ce message est transmis à `run_agent(chat_id, context, cron=True)` sans callback de progression. Le mode `cron=True` ajoute les consignes de `Prompt_Reminder.md` au prompt système.

## Cycle de vie

- Un rappel ponctuel est archivé après exécution.
- Un rappel récurrent calcule une nouvelle `next_run_at`.
- Les rappels annulés ou archivés sont purgés après 48 heures.

## Interface fonctionnelle côté tools

Le LLM agit sur les rappels via quatre tools dédiés:

- `create_reminder`;
- `list_reminders`;
- `update_reminder`;
- `cancel_reminder`.

## Points d'attention

- Le scheduler, les tools reminders et le prompt reminder doivent évoluer ensemble.
- Le déclenchement doit rester auto-suffisant: l'agent doit comprendre pourquoi il s'exécute sans devoir relister les rappels pour se recontextualiser.
