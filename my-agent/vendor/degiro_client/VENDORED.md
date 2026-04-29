# Vendored `degiro_client`

Copie alignee sur [Degiro-API](../../../../../Degiro-API) synchronisee a la main.
Source: `Degiro-API/src/degiro_client/` (workspace local).

## Raison du vendoring

L'add-on HA tourne dans une image Docker Alpine autonome : pas de
`pip install file://` possible en build. On copie le code au depot pour que
l'image se construise sans dependance externe.

## Modifications vs upstream

- `__main__.py`, `cli.py`, `totp_migration.py` **non copies** (utilitaires CLI
  inutiles au runtime add-on).
- `client.py` et `orders.py` exposent `place_order`, `check_order`,
  `confirm_order`, `cancel_order` (alignes upstream). La defense en
  profondeur n'est plus au niveau du vendor : elle est faite cote
  application via la table `pending_actions`, le callback inline-keyboard
  Telegram et les garde-fous deterministes (chat_id autorise, kill switch
  `cfg.degiro_orders_enabled`, TTL 5 min, plafond 1500 EUR sur BUY, quota
  rolling 24h sur BUY). Voir `docs/fonctionnel/ordres-degiro.md`.

## Limitations connues du backend Degiro

- `price_history()` renvoie des candles **close-only**. Les champs
  `open`, `high`, `low`, `volume` du modele `Candle` existent mais ne sont pas
  peuples. Cote HA-Agent, les indicateurs sont implementes close-only.
- `resolution="P1W"` cote requete revient en pratique comme `P7D` dans la
  reponse. HA-Agent adopte `P7D` comme resolution canonique pour l'hebdo.
- L'URL charting VWD est appelee avec `tz=Europe/Paris` et renvoie des
  `datetime` naifs. HA-Agent convertit explicitement en UTC avant persistance
  SQLite.
- Le backend chart distingue deux types d'identifiants via le champ
  `vwdIdentifierType` du payload produit : `issueid` pour les titres EU,
  `vwdkey` pour les titres US (et certains ETF). Le parametre `series` de
  l'URL chart doit utiliser le prefixe correspondant — sinon le backend ne
  renvoie aucune serie. `price_now`, `price_history` et `price_metadata`
  acceptent un parametre `vwd_identifier_type` qui par defaut vaut `issueid`.

## Comment resynchroniser

1. `cp -r Degiro-API/src/degiro_client/ HA-Agent/my-agent/vendor/degiro_client/`
2. Supprimer `__main__.py`, `cli.py`, `totp_migration.py`.
3. Verifier que `client.py` et `orders.py` exposent toujours les methodes
   d'ordre (`place_order`, `check_order`, `confirm_order`, `cancel_order`)
   et que les constantes d'`endpoints.py` (`CHECK_ORDER_PATH`, `ORDER_PATH`,
   `ORDER_ACTIONS`, `ORDER_TYPES`, `TIME_TYPES`) sont presentes.
4. Mettre a jour la section "Commit source" ci-dessous.

## Commit source

Synchronise depuis le workspace local (pas de repo git distant). Dernier
sync avec les correctifs :
- `prices.py:price_history` : offsets float (pas int) pour supporter PT10M.
- `client.py:price_metadata(vwd_id)` : wrapper public stable sur
  `prices.metadata()`.
