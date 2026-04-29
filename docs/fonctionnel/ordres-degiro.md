# Ordres Degiro via Telegram (human-in-the-loop)

Cette page décrit le passage et l'annulation d'ordres sur Degiro depuis l'agent. La règle structurante : **le LLM ne déclenche jamais l'exécution d'un ordre**. Il propose, l'humain confirme via un bouton inline Telegram, et c'est le code applicatif (hors boucle agent) qui appelle Degiro.

## Vue d'ensemble du flow

```
LLM tool (degiro_propose_order / degiro_propose_cancel)
   └─> agent/orders.py : insert pending_actions (status=pending, expires_at=now+5min)
        └─> agent/telegram.py : send_order_confirmation -> InlineKeyboardMarkup [Confirmer / Annuler]

Clic utilisateur sur le bouton
   └─> CallbackQueryHandler -> handle_order_callback
        └─> orders.resolve_pending : UPDATE conditionnel WHERE status='pending' (idempotent)
             ├─> action='place'  -> degiro.place_limit_gtc(...)
             └─> action='cancel' -> degiro.cancel_order(order_id)
        └─> edit du message Telegram avec le résultat
```

Le LLM n'a accès à aucune fonction d'exécution. Les seuls points qui appellent réellement le client Degiro pour passer/annuler un ordre se trouvent dans `agent/orders.py:resolve_pending`, déclenché uniquement par un clic Telegram authentifié.

## Tools LLM exposés

Les trois tools ne sont enregistrés que si `cfg.degiro_orders_enabled = true` (kill switch). Sinon ils ne figurent pas dans le schéma OpenAI envoyé au modèle.

- `degiro_propose_order(query, side, size, limit_price)` : résout le produit (`degiro.resolve_product`), valide les garde-fous, insère la ligne `pending_actions`, envoie le message Telegram avec inline keyboard. Retourne au LLM un accusé `Demande #N envoyée…` mais n'attend aucune confirmation.
- `degiro_list_open_orders()` : lecture seule des ordres non encore exécutés (`client.get_orders(historical=False)`).
- `degiro_propose_cancel(order_id)` : vérifie que l'`order_id` figure dans la liste des ordres ouverts, insère la ligne `pending_actions` de type `cancel`, envoie le message Telegram. Même flow que `propose_order` côté humain.

## Caractéristiques fixes des ordres

- **Type d'ordre** : `LIMIT` uniquement (`LIMITED`, code Degiro 0). Pas de MARKET, pas de STOP.
- **Validité** : `PERMANENT` (GTC, code Degiro 3). Les ordres restent ouverts jusqu'à exécution ou annulation manuelle.
- **TTL pending** : 5 minutes. Au-delà, le scheduler marque la ligne `expired` et désactive le bouton.

## Garde-fous déterministes

Tous appliqués par `agent/orders.py` **avant** insertion en base, **et** revérifiés au moment du `resolve_pending` (claim conditionnel sur `status='pending' AND expires_at > now AND chat_id = ?`).

| Garde-fou | Portée | Détail |
|-----------|--------|--------|
| Kill switch | tous les ordres et annulations | `cfg.degiro_orders_enabled = true` requis. Source : option add-on `degiro_orders_enabled`. |
| `chat_id` autorisé | callback Telegram | doit appartenir à `cfg.telegram_allowed_chat_ids`. |
| Plafond | BUY uniquement | `size × limit_price ≤ 1500 EUR`. Aucune contrainte sur les SELL. |
| Quota | BUY uniquement | maximum 4 ordres BUY confirmés sur une fenêtre glissante de 24h (`resolved_at >= now - 24h`). Compte uniquement les ordres effectivement transmis à Degiro (statut `confirmed`). |
| TTL | tous les pending | 5 min. La fenêtre se ferme côté DB via `expires_at`, le bouton devient inerte. |
| Idempotence | confirmation | UPDATE conditionnel `status='pending'` : seul le premier clic gagne. Un second clic répond `Déjà confirmé/annulé`. |

Les SELL ne sont contraints que par le kill switch, le `chat_id` autorisé et le TTL — pas de plafond €, pas de quota. Choix assumé : permettre d'évacuer une position rapidement.

## Persistance : table `pending_actions`

Définie dans `agent/db.py:init_db`. Une seule ligne par demande, qu'il s'agisse d'un placement ou d'une annulation.

| Colonne | Notes |
|---------|-------|
| `id` | clé primaire utilisée comme nonce dans `callback_data`. |
| `chat_id` | propriétaire de la demande, vérifié au callback. |
| `action` | `place` ou `cancel`. |
| `payload_json` | params normalisés (product_id, isin, label, side, size, limit_price, currency) ou (order_id, label). |
| `preview_text` | texte affiché dans le message Telegram. |
| `status` | `pending` → `confirmed` / `cancelled` / `expired` / `failed`. |
| `telegram_message_id` | rempli juste après l'envoi pour pouvoir éditer le message. |
| `result_text` | `orderId=…` côté Degiro, ou trace d'erreur si exception. |
| `created_at`, `expires_at`, `resolved_at` | UTC ISO 8601. |

Index : `(status, expires_at)` pour le scheduler d'expiration, `(chat_id, action, resolved_at)` pour le calcul du quota.

## Configuration

- Option add-on `degiro_orders_enabled` (bool, défaut `false`) → variable d'environnement `DEGIRO_ORDERS_ENABLED` exportée par `run.sh` → `cfg.degiro_orders_enabled`.
- Active à la fois l'enregistrement des tools côté LLM et l'autorisation d'exécution. Désactiver à chaud bloque toute nouvelle proposition (les pending déjà en file expirent normalement).
- L'option `degiro_*` (username/password/totp_seed) est un prérequis : sans credentials, les tools ne sont pas chargés du tout (cf. `main.py`).

## Versions et points de vigilance

- Le vendor `my-agent/vendor/degiro_client/` expose désormais `place_order` / `check_order` / `confirm_order` / `cancel_order` (`VENDORED.md` à jour). La défense n'est plus au niveau vendor mais au niveau applicatif.
- Le scheduler appelle `orders.expire_due_pending()` à chaque tick (`agent/scheduler.py:expire_pending_orders`) et édite le message Telegram pour refléter l'expiration.
- `degiro.place_limit_gtc` repose sur la même session singleton que les tools de lecture. Si Degiro renvoie une erreur de session, la prochaine `get_client()` relance un login automatique (cf. `agent/degiro.py`).
- L'agent peut être appelé sans context Telegram (rappels cron, etc.). Les tools `degiro_propose_order` / `degiro_propose_cancel` détectent l'absence de `chat_id` dans `_context` et renvoient une erreur explicite : la confirmation humaine est inopérante hors Telegram.

Pour les évolutions, garder les tests `tests/test_orders.py` à jour (idempotence, quota, plafond, expiration, isolation par `chat_id`).
