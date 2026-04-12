# Agent loop et prompt

## Boucle agent

Le point d'entrée métier est `run_agent(chat_id, user_message, cron=False, progress_callback=None)`.

Le déroulé attendu est:

1. vérifier si la session courante a expiré et, si oui, l'archiver logiquement;
2. sauvegarder le message utilisateur;
3. construire le prompt système standard ou cron;
4. charger l'historique de session utile;
5. appeler le modèle courant avec les tools disponibles;
6. exécuter chaque `tool_call`, puis relancer le modèle avec les résultats;
7. journaliser les tokens consommés;
8. sauvegarder la réponse assistant et la renvoyer.

Les messages de tools ne sont pas persistés comme historique utilisateur/assistant. Ils ne vivent que dans l'exécution courante.

## Construction du prompt

Le prompt est reconstruit à chaque requête à partir des fichiers du workspace. L'ordre logique est le suivant:

1. contexte runtime, avec date, timezone et consignes liées au run; si le petit modèle est actif et distinct du modèle principal, une consigne d'escalade est ajoutée à ce bloc (voir `routage-modele.md`);
2. `AGENT.md`;
3. `USER.md`;
4. `chats/<chat_id>.md` si un contexte spécifique existe pour la conversation courante;
5. un index compact des `skills/*/SKILL.md`;
6. `MEMORY.md`;
7. résumé des derniers tool calls récents pour le `chat_id` courant — soumis à la configuration `include_recent_tool_calls` (voir section dédiée ci-dessous).

Les blocs sont assemblés avec des séparateurs explicites. En mode rappel planifié, `Prompt_Reminder.md` est ajouté à la fin.

Le contexte `chats/<chat_id>.md` est optionnel et ciblé par identifiant Telegram exact. Il permet d'ajouter des consignes propres à une conversation donnée sans polluer le prompt global de `AGENT.md` ou le profil durable de `USER.md`.

## Index des skills

Le prompt n'embarque pas le contenu complet des skills. Il injecte une section `Skills Index` qui liste chaque skill avec:

- le nom du dossier;
- une courte description;
- le chemin absolu du `SKILL.md` à lire si besoin.

La description injectée suit une règle déterministe:

1. texte sous `## Purpose`;
2. sinon premier bullet de `## Use This Skill When`;
3. sinon première ligne non vide utile;
4. sinon `No description available.`

Le prompt rappelle explicitement à l'agent qu'il doit lire le `SKILL.md` avec `read_file` avant de suivre une skill dont il n'a que l'index.

## Gestion de session

- Le timeout de session est configurable via `session_timeout_hours` et vaut `48` heures par défaut.
- La fenêtre de contexte est configurable via `max_session_messages` et vaut `15` messages par défaut.
- Au maximum `15` messages user/assistant récents, ou la valeur configurée, sont envoyés au LLM si la session courante n'a pas expiré.
- Après expiration du timeout, la session courante est archivée logiquement et aucun message précédent n'est envoyé à l'agent pour le run suivant.
- Les horodatages sont stockés en UTC ISO 8601. L'heure locale sert aux affichages et au prompt runtime.

Note d'évolution souhaitable: ajouter à terme une capacité explicite pour l'agent à rechercher dans l'historique archivé quand c'est utile, plutôt que de limiter l'accès au seul contexte de session actif. Cette capacité n'est pas implémentée aujourd'hui.

## Historique récent de tools

Le prompt peut injecter les derniers tool calls du chat courant afin d'éviter les répétitions inutiles entre runs proches. La fenêtre documentaire actuelle est:

- 5 tool calls maximum;
- âgés de moins de 3 heures.

Ce mécanisme complète `MEMORY.md`: il sert au contexte opérationnel de court terme, pas à la mémoire durable.

L'injection de cette section est contrôlée par l'option add-on `include_recent_tool_calls`:

- `true`: la section `Recent Tool Calls` est ajoutée si des appels récents existent;
- `false`: la section n'est jamais injectée.

Le compromis est volontaire: activer cette section peut améliorer la continuité à court terme, mais fait varier le prompt système plus souvent et peut donc réduire l'efficacité du prompt caching.

## Journalisation des tokens

La consommation est stockée par modèle dans `token_usage`. Les `cached_tokens` sont suivis séparément pour refléter le prompt caching OpenAI et permettre un affichage de coût plus fidèle dans le dashboard.

## Points d'attention

- Toute évolution de structure du prompt doit rester cohérente avec le contenu de `workspace-et-memoire.md`.
- Toute évolution de la boucle qui change le modèle courant ou la visibilité des tools doit rester cohérente avec `routage-modele.md` et `tools.md`.
