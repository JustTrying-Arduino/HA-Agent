# Telegram

## Rôle

Telegram est l'interface conversationnelle principale de l'agent. Le bot fonctionne en polling et ne dépend pas d'un webhook ni d'une exposition réseau supplémentaire.

## Parcours standard

Lorsqu'un message entre:

1. le bot valide que le chat est autorisé;
2. il crée rapidement un message temporaire de statut;
3. il lance `run_agent(...)`;
4. il met à jour le statut uniquement pour certains tools longs ou visibles;
5. il remplace le placeholder par la réponse finale, ou le supprime si la réponse doit être envoyée en plusieurs messages.

Le comportement recherché est une UX sobre: un seul placeholder, peu de bruit, pas de streaming token par token.

## Placeholder de progression

Le bot envoie immédiatement un court message de type `En reflexion...` pour signaler la prise en charge. Ce message peut être réutilisé pour afficher des phases lentes comme:

- recherche web;
- récupération de page web;
- exécution shell.
- lecture ou commande Home Assistant.

Les tools rapides ou peu visibles n'ont pas vocation à générer de bruit côté Telegram.

## Réponse finale

- Si la réponse tient dans un seul message Telegram, le placeholder est édité en réponse finale.
- Si elle dépasse cette limite, le placeholder est supprimé puis la réponse est envoyée en morceaux.
- Si l'agent génère une réponse vide (silence intentionnel), le placeholder est supprimé et aucun message n'apparaît dans Telegram.
- Les réponses finales peuvent utiliser un sous-ensemble HTML Telegram piloté par le prompt: `<b>`, `<i>`, `<code>`, `<pre>`, `<a href="...">`.
- Ce formatage riche ne s'applique qu'aux réponses finales. Les placeholders et statuts de progression restent en texte brut.
- Le découpage des réponses longues préserve autant que possible les blocs de paragraphes et évite de casser un bloc HTML valide au milieu.
- Si un bloc formaté dépasse la limite Telegram ou si Telegram rejette le rendu HTML, le bot retombe automatiquement en texte brut pour garantir la livraison du contenu.

## Contrat de formatage

Le prompt système autorise uniquement un HTML léger, adapté à Telegram:

- `<b>` pour de courts libellés ou micro-titres;
- `<i>` pour une emphase légère;
- `<code>` pour commandes, chemins, variables et identifiants;
- `<pre>` pour de courts blocs shell, log ou code;
- `<a href="...">` pour les liens.

Le backend ne tente pas de "réparer" un HTML libre ou arbitraire. Il applique le rendu demandé, puis bascule en texte brut si l'envoi ou l'édition échoue.

## Messages vocaux

Les messages audio sont transcrits avant passage dans la boucle agent. La transcription repose sur `audio.py`, qui est une utilité interne et non un tool exposé au LLM.

## Contraintes à préserver

- Mode de connexion: polling uniquement.
- Faible verbosité côté bot pendant le run.
- Les libellés de progression visibles par l'utilisateur sont distincts des noms techniques internes des tools.
