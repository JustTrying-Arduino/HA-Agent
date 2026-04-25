# Veille boursiere

## Perimetre

La veille boursiere repose desormais sur Degiro: donnees close-only intraday (PT10M, PT15M, PT1H), daily (P1D) et hebdomadaire (P7D). Le flux est directement branche au compte courtier de l'utilisateur, donc pas de quota externe a surveiller. Marketstack n'est plus utilise et son plan gratuit etait de toute facon trop serre pour un scan quotidien type CAC40 + US.

## Source de donnees

- Bibliotheque `degiro_client` vendored sous `my-agent/vendor/degiro_client/` (depuis `Degiro-API`).
- La copie vendored est **strip** de toutes les methodes d'ordre (`place_order`, `check_order`, `confirm_order`, `cancel_order`). L'agent **ne peut pas** passer d'ordre.
- Provider singleton: `agent/degiro.py`. Gere le login initial, le relogin auto (25 min d'inactivite), et la detection de changement de credentials via fingerprint HMAC-SHA256 persiste dans `/data/degiro/.creds_fingerprint`.
- Timestamps: Degiro renvoie des `datetime` naifs en heure Paris. Le provider convertit systematiquement en UTC (via `zoneinfo.ZoneInfo("Europe/Paris")`) avant persistance SQLite.

### Limitation close-only

- `price_history()` renvoie **uniquement `close` et `timestamp`**. `open`, `high`, `low`, `volume` ne sont jamais peuples.
- Les indicateurs disponibles sont donc close-only: pas de confirmations "volume au retournement" ou "volume sur breakout" cote tool.
- Pour un breakout douteux, croiser avec `web_search` / `web_fetch`.

### Anomalie `P1W` / `P7D`

Degiro accepte `resolution=P1W` en requete mais renvoie `P7D` dans la serie. HA-Agent traite `P7D` comme la resolution canonique hebdomadaire.

## Tools exposes

- `market_watch(strategy, group=?, max_candidates=?)`: screener par strategie (`rebound` ou `swing`) sur la watchlist. Renvoie candidats, rejets (falling knives pour rebound), neutres.
- `degiro_portfolio(include_closed=?)`: snapshot du portefeuille (positions, cash, P&L jour et cumulatif). Accepte les lignes `FLATEX_EUR` et les positions sans historique.
- `degiro_search(query, limit=?)`: resolution symbole / ISIN / currency.
- `degiro_quote(query)`: prix courant, variation jour, drawdown vs 52w high, distance au 52w low, via `price_metadata()`.
- `degiro_candles(query, window=?, limit=?)`: serie close-only, fenetres `today-10m`, `5d-1h`, `1m-1d`, `3m-1d`, `1y-1d`, `5y-1w`.
- `degiro_indicators(query, strategy)`: verdict structure (signal + score + raisons + metriques brutes) pour `rebound` ou `swing`.

## Cache SQLite

Deux tables locales (creees par `agent/db.py`):

- `degiro_products`: `PRIMARY KEY(query_norm)`. Cache de resolution produit avec flags `history_ok`, `metadata_ok`. TTL 7 jours.
- `degiro_prices`: **close-first**, `PRIMARY KEY(vwd_id, resolution, ts)`. `close NOT NULL`, `open/high/low/volume` nullables (reserves pour compat future). TTL par resolution: intraday 5 min, H1 30 min, daily 8 h, hebdo 24 h.

Les tables `market_eod_prices` et `market_api_usage` sont supprimees (DROP au boot).

## Strategies

### Rebond
- RSI(14) < 30 (marque "extreme" si < 20).
- Drawdown vs `highPriceP1Y` (seuil defaut -20 %).
- Proximite d'un niveau de support dense (clustering des closes).
- Debut de reprise: close(t) > close(t-1) ou stabilisation sur 2-3 points.
- Rejet automatique "falling knife" si cluster de support casse (close < densest_level * 0.98) + RSI < 30 + pente SMA50 negative.

### Swing
- Tendance haussiere: close > SMA200 **et** SMA50 > SMA200.
- Pullback propre: |close - SMA50| / SMA50 ≤ 3 % sur fond de pente SMA50 positive.
- Reprise close-only: close(t) > close(t-1).
- Breakout close-only: close > max des 20 closes precedents (pas de critere volume).

Ces indicateurs sont implementes en Python pur dans `agent/indicators.py` (RSI Wilder, SMA, slope, breakout, support/resistance, evaluate_rebound, evaluate_swing).

## Watchlist

- Fichier workspace: `skills/market-watch/watchlist.json`.
- **Format ISIN-first**: `{ "isin": "...", "label": "...", "currency": "EUR", "exchange_id": "..." (optionnel) }`.
- `exchange_id` et `currency` sont fortement recommandes pour desambiguer les listings multiples (ADR, XETRA, Euronext...).
- Groupes fournis: `core_daily`, `us_key`.

## Pipeline de resolution produit

1. `search_products(query, limit=20)`.
2. Filtrage: ISIN exact > `exchange_id` > `currency` > presence de `vwd_id`.
3. Validation `price_history(vwd_id, period="P1M", resolution="P1D")`: ≥ 5 candles -> `history_ok=True`.
4. Validation `price_metadata(vwd_id)`: dict non vide -> `metadata_ok=True`.
5. Persistance `degiro_products`.

Les positions sans `vwd_id` ou sans historique sont affichees avec le prix actuel, mais `degiro_indicators` refuse explicitement d'analyser un produit dont `history_ok=False`.

## Why via web

Une fois les 1 a 3 candidats retenus:

1. `web_search` sur le nom / ticker.
2. `web_fetch` sur l'article le plus credible.
3. Distinguer baisse technique, news sectorielle, deterioration fondamentale.

## Points d'attention

- Toute evolution de la famille `degiro_*` ou de `market_watch` doit aussi mettre a jour `tools.md`, `portefeuille.md`, et les skills `market-watch` / `portfolio-advisor`.
- Toute evolution du format `watchlist.json` doit aussi mettre a jour `workspace-et-memoire.md`.
- Le client vendored doit rester **strip** des methodes d'ordre. Voir `my-agent/vendor/degiro_client/VENDORED.md`.
