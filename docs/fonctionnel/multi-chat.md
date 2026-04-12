# Multi-chat Telegram

## Rôle

Le système supporte plusieurs conversations Telegram distinctes en parallèle. Chaque conversation est isolée par son `chat_id`, qui devient la clé de séparation pour:

- l'autorisation d'accès côté bot;
- l'historique de session;
- les tool calls récents injectés au prompt;
- les rappels;
- le contexte workspace spécifique au chat;
- les vues filtrées du dashboard.

## Clé fonctionnelle

Le `chat_id` est l'identifiant canonique du chat courant. Il ne faut pas raisonner en termes d'utilisateur Telegram autorisé, mais bien en termes de conversation autorisée:

- message privé: `chat_id` du DM;
- groupe: `chat_id` propre au groupe, distinct des IDs personnels;
- supergroupe: souvent un ID négatif de type `-100...`.

Le bot reçoit déjà ce `chat_id` via Telegram et le propage jusqu'à la boucle agent.

## Effets côté agent

Le `chat_id` courant est utilisé pour:

- sauvegarder et relire les messages de session;
- rattacher les tool calls au bon chat;
- construire le prompt système avec le contexte du chat courant;
- exécuter les rappels dans la conversation d'origine.

Le prompt peut injecter un fichier optionnel `workspace/chats/<chat_id>.md`. Ce fichier permet d'ajouter des consignes durables propres à une conversation, sans impacter les autres chats.

## Workspace dédié

Le workspace persistant expose:

- `/share/myagent/workspace/chats/README.md`
- `/share/myagent/workspace/chats/<chat_id>.md`

Règles d'usage:

- nommer le fichier exactement avec le `chat_id`;
- garder un contenu court, stable et spécifique à cette conversation;
- ne pas y stocker des tâches temporaires mieux exprimées directement dans le chat.

## Dashboard

Le dashboard expose le multi-chat de façon simple:

- `Messages`: sous-onglets par `chat_id` + vue `Tous`;
- `Tool Calls`: même filtre par `chat_id` + colonne `Chat ID`;
- `Reminders`: la colonne `Chat` permet déjà d'identifier la conversation cible.

L'API expose aussi `/api/chats` pour lister les conversations connues et leur dernière activité.

## Points d'attention

- Toute nouvelle logique multi-chat doit rester basée sur `chat_id` comme clé unique.
- Ne pas introduire de mapping implicite par nom de groupe ou participants sans besoin explicite.
- Si une vue agrège plusieurs chats, elle doit toujours rendre l'origine (`chat_id`) visible.
