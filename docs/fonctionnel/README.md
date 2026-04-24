# Documentation fonctionnelle

Cette documentation décrit le fonctionnement du projet pour les IA et les développeurs qui le font évoluer. Chaque fichier couvre une thématique précise, avec peu de recouvrement et des renvois explicites quand un sujet touche plusieurs zones.

## Règles de maintenance

- Toute évolution fonctionnelle doit mettre à jour, dans le même changement, le ou les fichiers concernés de `docs/fonctionnel/`.
- Si un nouveau thème documentaire apparaît, ajouter son fichier ici puis le référencer aussi dans `CLAUDE.md`.
- Si une évolution touche plusieurs zones, mettre à jour tous les fichiers impactés, pas seulement le plus proche.
- Garder les fichiers courts, ciblés, et orientés comportement réel du système.

## Index

| Fichier | Quand le consulter |
|---------|--------------------|
| [`architecture-globale.md`](./architecture-globale.md) | Pour comprendre la vue d'ensemble, les composants, les flux principaux et les choix d'architecture. |
| [`agent-loop-et-prompt.md`](./agent-loop-et-prompt.md) | Pour modifier la boucle agent, le contexte envoyé au LLM, la gestion de session ou l'historique injecté. |
| [`routage-modele.md`](./routage-modele.md) | Pour faire évoluer la logique de bascule entre modèle léger et modèle principal. |
| [`telegram.md`](./telegram.md) | Pour tout changement sur le parcours Telegram: polling, placeholder, réponse finale, audio. |
| [`multi-chat.md`](./multi-chat.md) | Pour les comportements liés au `chat_id`, à l'isolation entre conversations Telegram et au contexte spécifique par chat. |
| [`dashboard.md`](./dashboard.md) | Pour les évolutions du dashboard, des endpoints JSON et des comportements front. |
| [`homeassistant.md`](./homeassistant.md) | Pour l'intégration Supervisor, les tools HA natifs, le filtrage par label et la config associée. |
| [`reminders.md`](./reminders.md) | Pour les rappels planifiés, le scheduler et le déclenchement des runs cron. |
| [`tools.md`](./tools.md) | Pour ajouter ou modifier des tools, leurs règles d'exposition, leurs limites et leur exécution. |
| [`veille-boursiere.md`](./veille-boursiere.md) | Pour le suivi boursier via Degiro (close-only), le cache local, la watchlist ISIN-first et les stratégies rebond / swing. |
| [`portefeuille.md`](./portefeuille.md) | Pour la lecture du portefeuille Degiro, le skill `portfolio-advisor`, la règle « jamais d'ordre » et les limitations close-only. |
| [`workspace-et-memoire.md`](./workspace-et-memoire.md) | Pour les fichiers workspace, la mémoire durable, les skills et leur cycle de vie. |

## Frontière avec les autres docs

- `README.md` reste orienté utilisateur et installation.
- `CLAUDE.md` reste le point d'entrée de contribution: règles globales, conventions, mini résumé d'architecture et index documentaire.
