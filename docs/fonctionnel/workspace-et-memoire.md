# Workspace et memoire

## Emplacement et persistance

Le workspace fonctionnel de l'agent vit dans `/share/myagent/workspace/`. Il est persistant entre les redémarrages et doit rester éditable depuis Home Assistant, Samba ou SSH.

Les fichiers présents dans `my-agent/workspace/` servent de templates initiaux copiés au premier démarrage. Ils ne doivent pas être écrasés automatiquement ensuite.

## Fichiers structurants

- `AGENT.md`: identité de l'agent, règles de comportement, ton et contraintes générales.
- `USER.md`: informations durables sur l'utilisateur, préférences et habitudes stables.
- `MEMORY.md`: contexte durable non strictement utilisateur, projets en cours, décisions à retenir.
- `Prompt_Reminder.md`: consignes spécifiques aux runs déclenchés par rappel.
- `chats/<chat_id>.md`: contexte durable spécifique à une conversation Telegram précise.
- `skills/<name>/SKILL.md`: compétences étroites, actionnables, spécialisées.

## Règles d'usage

- `AGENT.md` doit rester concis et stable.
- `USER.md` ne doit contenir que des faits durables utiles à l'assistance future.
- `MEMORY.md` ne remplace pas l'historique de session: il sert au long terme.
- `chats/<chat_id>.md` ne doit contenir que des consignes stables ou récurrentes propres à ce chat.
- Une skill doit être ciblée, autonome, et éviter de devenir un journal ou une mémoire fourre-tout.

## Relation avec le prompt

Le contenu du workspace est relu à chaque requête pour reconstruire le prompt système. Toute évolution d'un de ces fichiers a donc un impact direct et immédiat sur le comportement de l'agent, sans rebuild de l'add-on.

`AGENT.md`, `USER.md`, `MEMORY.md`, `Prompt_Reminder.md` et éventuellement `chats/<chat_id>.md` peuvent être injectés directement selon le type de run. Dans le prompt final, les blocs issus de `AGENT.md`, `USER.md`, `MEMORY.md` et `Prompt_Reminder.md` sont intitulés avec leur nom de fichier. Le contexte spécifique au chat courant est présenté sous l'intitulé `Current Chat Specific Context` plutôt que par son chemin de fichier. Les skills, elles, ne sont pas injectées en entier: le prompt embarque seulement un index compact construit depuis leurs `SKILL.md`, puis l'agent lit le fichier complet à la demande via `read_file` si une skill semble pertinente.

## Relation avec la memoire recente

Le workspace porte la mémoire durable. Le contexte opérationnel court terme, lui, vient des messages de session et, si l'option add-on `include_recent_tool_calls` est activée, des récents tool calls injectés par la boucle de prompt. Ces deux couches sont complémentaires et ne doivent pas être confondues.

## Points d'attention

- Toute évolution du format ou du rôle d'un fichier workspace doit être répercutée dans `agent-loop-et-prompt.md`.
- Toute nouvelle catégorie de contenu persistant doit être documentée ici avant d'être considérée comme établie.
