# Vendored `degiro_client`

Read-only copy of [Degiro-API](../../../../../Degiro-API) synchronisee a la main.
Source: `Degiro-API/src/degiro_client/` (workspace local).

## Raison du vendoring

L'add-on HA tourne dans une image Docker Alpine autonome : pas de
`pip install file://` possible en build. On copie le code au depot pour que
l'image se construise sans dependance externe.

## Modifications vs upstream

- `__main__.py`, `cli.py`, `totp_migration.py` **non copies** (utilitaires CLI
  inutiles au runtime add-on).
- `client.py` et `orders.py` **strippes** des methodes qui permettent de passer
  des ordres (`place_order`, `check_order`, `confirm_order`, `cancel_order`).
  Defense en profondeur : meme si une prompt injection tentait
  `client.place_order(...)`, la methode n'existe simplement pas.
- `get_orders()` (lecture de l'historique) est **conserve**.

## Limitations connues du backend Degiro

- `price_history()` renvoie des candles **close-only**. Les champs
  `open`, `high`, `low`, `volume` du modele `Candle` existent mais ne sont pas
  peuples. Cote HA-Agent, les indicateurs sont implementes close-only.
- `resolution="P1W"` cote requete revient en pratique comme `P7D` dans la
  reponse. HA-Agent adopte `P7D` comme resolution canonique pour l'hebdo.
- L'URL charting VWD est appelee avec `tz=Europe/Paris` et renvoie des
  `datetime` naifs. HA-Agent convertit explicitement en UTC avant persistance
  SQLite.

## Comment resynchroniser

1. `cp -r Degiro-API/src/degiro_client/ HA-Agent/my-agent/vendor/degiro_client/`
2. Supprimer `__main__.py`, `cli.py`, `totp_migration.py`.
3. Retirer de `client.py` : `place_order`, `check_order`, `confirm_order`,
   `cancel_order` (methodes de l'instance).
4. Retirer de `orders.py` : fonctions `check_order`, `confirm_order`,
   `place_order`, `cancel_order`. Conserver `get_orders` et `_unflatten`
   utilise par `portfolio.py`.
5. Mettre a jour la section "Commit source" ci-dessous.

## Commit source

Synchronise depuis le workspace local (pas de repo git distant). Dernier
sync avec les correctifs :
- `prices.py:price_history` : offsets float (pas int) pour supporter PT10M.
- `client.py:price_metadata(vwd_id)` : wrapper public stable sur
  `prices.metadata()`.
