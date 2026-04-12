# Dashboard

## Rôle

Le dashboard expose une vue d'audit et de suivi de l'agent depuis Home Assistant ingress. Il lit les données SQLite via une API JSON servie par `aiohttp`.

## Structure générale

Le front est volontairement simple: un seul fichier HTML avec JavaScript natif, sans framework ni build step. Les URLs API sont relatives pour rester compatibles avec l'ingress Home Assistant. L'en-tête et la barre d'onglets sont sticky.

Quatre onglets principaux:

---

## Onglet Tokens

**Objectif:** suivre la consommation de tokens et les coûts estimés par modèle et par période.

**Sélecteur de période:** jour / semaine / mois (appel à `/api/stats?period=day|week|month`).

**Données affichées par entrée:**
- période et modèle;
- tokens input, output, cached;
- coût estimé en USD (calculé côté serveur: input non-caché au tarif plein, input caché au tarif réduit, output au tarif output).

---

## Onglet Messages

**Objectif:** auditer l'historique conversationnel par chat.

**Sous-onglets:** un par `chat_id` connu + vue globale `Tous` (appel à `/api/messages?chat_id=X&limit=50`).

**Données affichées par message:**
- rôle (user / assistant) avec badge coloré;
- badge `Chat ID`;
- horodatage au format `dd/mm HH:MM`;
- contenu du message;
- badge modèle sur les réponses assistant quand l'information est disponible.

Les tool calls exécutés dans la même minute qu'un message assistant sont affichés en dessous de celui-ci, avec nom du tool, durée et résumé du résultat (extensible). Un bouton `Charger plus` permet de paginer l'historique.

---

## Onglet Tool Calls

**Objectif:** auditer l'ensemble des appels d'outils, indépendamment de la vue messages.

**Sous-onglets:** un par `chat_id` connu + vue globale `Tous` (appel à `/api/tool_calls?chat_id=X&limit=50`).

**Colonnes de la table:**
- heure (`dd/mm HH:MM`);
- Chat ID;
- nom du tool;
- input (tronqué, extensible au clic);
- statut (✓ succès / ✗ échec);
- durée en ms.

---

## Onglet Reminders

**Objectif:** visualiser et filtrer les rappels planifiés tous chats confondus.

**Filtre de statut:** Tous / Actifs / Archivés / Annulés (appel à `/api/reminders?status=active|all`).

**Colonnes de la table:**
- ID;
- Chat ID;
- statut (pill coloré: vert actif, orange archivé, rouge annulé);
- titre;
- instruction (tronquée, extensible au clic);
- prochaine exécution;
- dernière exécution;
- date d'archivage.

---

## Développement local

Le front bascule sur des mocks intégrés si l'API n'est pas joignable. Ce fallback sert uniquement au développement front hors backend et ne modifie pas le comportement en production.

## Points d'attention

- Toute évolution d'un endpoint doit être répercutée dans le front et dans cette documentation.
- Toute donnée ajoutée au dashboard doit préciser son origine en base ou dans la boucle agent.
