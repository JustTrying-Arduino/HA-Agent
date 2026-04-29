# Veille boursiere

## Perimetre

La veille boursiere repose desormais sur Degiro: donnees close-only intraday (PT10M, PT15M, PT1H), daily (P1D) et hebdomadaire (P7D). Le flux est directement branche au compte courtier de l'utilisateur, donc pas de quota externe a surveiller. Marketstack n'est plus utilise et son plan gratuit etait de toute facon trop serre pour un scan quotidien type CAC40 + US.

## Source de donnees

- Bibliotheque `degiro_client` vendored sous `my-agent/vendor/degiro_client/` (depuis `Degiro-API`).
- La copie vendored est **strip** de toutes les methodes d'ordre (`place_order`, `check_order`, `confirm_order`, `cancel_order`). L'agent **ne peut pas** passer d'ordre.
- Provider singleton: `agent/degiro.py`. Gere le login initial, le relogin auto (25 min d'inactivite), et la detection de changement de credentials via fingerprint HMAC-SHA256 persiste dans `/data/degiro/.creds_fingerprint`.
- Timestamps: Degiro renvoie des `datetime` naifs en heure Paris. Le provider convertit systematiquement en UTC (via `zoneinfo.ZoneInfo("Europe/Paris")`) avant persistance SQLite.

### Limitation close-only

- "close-only" porte sur le contenu de chaque candle, **pas** sur la granularite temporelle: les variations intra-journee restent accessibles via `PT10M` / `PT15M` / `PT1H` (chaque tick = un close).
- `price_history()` renvoie **uniquement `close` et `timestamp`**. `open`, `high`, `low`, `volume` ne sont jamais peuples.
- Les indicateurs disponibles sont donc close-only: pas de confirmations "volume au retournement" ou "volume sur breakout" cote tool.
- Pour un breakout douteux, croiser avec `web_search` / `web_fetch`.

### Anomalie `P1W` / `P7D`

Degiro accepte `resolution=P1W` en requete mais renvoie `P7D` dans la serie. HA-Agent traite `P7D` comme la resolution canonique hebdomadaire.

## Tools exposes

- `market_watch(strategy, group=?, max_candidates=?)`: screener par strategie (`rebound` ou `swing`) sur la watchlist. Renvoie candidats, **recoveries** (rebonds deja avances, hors scope d'entree), rejets (falling knives pour rebound), neutres. Bandeau de fraicheur en tete (`last_bar_max`, nombre de bougies provisoires).
- `degiro_portfolio(include_closed=?)`: snapshot du portefeuille (positions, cash, P&L jour et cumulatif). Accepte les lignes `FLATEX_EUR` et les positions sans historique.
- `degiro_search(query, limit=?)`: resolution symbole / ISIN / currency.
- `degiro_quote(query)`: prix courant, variation jour, drawdown vs 52w high, distance au 52w low, via `price_metadata()`.
- `degiro_candles(query, window=?, limit=?)`: serie close-only, fenetres `today-10m`, `5d-1h`, `1m-1d`, `3m-1d`, `1y-1d`, `5y-1w`.
- `degiro_indicators(query, strategy)`: verdict structure (signal + score + raisons + metriques brutes) pour `rebound` ou `swing`.
- `degiro_chart(query, window=?)`: genere un PNG (line chart, fill, vert/rouge selon variation) via QuickChart.io et l'envoie au chat Telegram. Memes fenetres que `degiro_candles`. Downsampling uniforme a ≤ 250 points (limite anonyme du service).

## Cache SQLite

Deux tables locales (creees par `agent/db.py`):

- `degiro_products`: `PRIMARY KEY(query_norm)`. Cache de resolution produit avec flags `history_ok`, `metadata_ok`. TTL 7 jours.
- `degiro_prices`: **close-first**, `PRIMARY KEY(vwd_id, resolution, ts)`. `close NOT NULL`, `open/high/low/volume` nullables (reserves pour compat future). TTL par resolution: intraday 5 min, H1 30 min, daily 8 h, hebdo 24 h.

Les tables `market_eod_prices` et `market_api_usage` sont supprimees (DROP au boot).

### Fraicheur de la bougie du jour (market-hours-aware)

`load_candles(..., currency=...)` evite de servir une bougie daily du jour qui ne serait pas encore settled:

- Heures de settle (helper `is_today_bar_settled(currency)` dans `agent/degiro.py`):
  - currency `USD` (NYSE / NASDAQ) -> settle a partir de **22h30 Paris**.
  - sinon (Euronext-like) -> settle a partir de **18h05 Paris**.
- Si la derniere `ts` cachee est aujourd'hui (Paris) **et** que le marche n'est pas encore settled, le tool **force un refresh** quel que soit le TTL de 8h.
- Cote outils analytiques (`degiro_indicators`, `market_watch`), `build_close_series(...)` greffe en plus la **derniere bougie intraday** (`today-10m`) comme bougie provisoire quand le close du jour manque ou n'est pas settled. La sortie expose `bar_ts` et `provisional=True/False` par titre, plus un bandeau global `last_bar_max` / `provisional=N/M`.

Effet: les indicateurs reflètent l'etat du marche **a l'heure ou le tool est appele**, et pas l'instantane fige par une session precedente.

## Strategies

### Rebond
- **Gate RSI strict**: si RSI(14) > 35 -> signal `neutral` immediat. Le label "rebond" implique survente.
- **Filtre anti-rattrapage**: si `var_3d` > +4 % -> signal `recovery` (rebond deja avance, hors scope d'entree).
- Drawdown vs `highPriceP1Y` (seuil defaut -20 %).
- Proximite d'un niveau de support dense (clustering des closes).
- **Bounce pondere**: var_1d entre +0,3 % et +2 % sur la derniere seance -> +1 point. Au-dessus de +2 %, la bougie est flaggee "too stretched" et n'apporte pas de point.
- Rejet automatique `reject` ("falling knife") si cluster de support casse (close < densest_level * 0.98) + RSI < 30 + pente SMA50 negative. Court-circuite tous les autres tests.
- Seuil de declenchement `candidate`: score >= 3.

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
3. Lecture du `vwdIdentifierType` (issueid pour EU, vwdkey pour US/ETF) — sans cette info, le backend chart ne renvoie aucune serie.
4. Validation `price_history(vwd_id, period="P1M", resolution="P1D", vwd_identifier_type=...)`: ≥ 5 candles -> `history_ok=True`.
5. Validation `price_metadata(vwd_id, vwd_identifier_type=...)`: dict non vide -> `metadata_ok=True`.
6. Persistance `degiro_products` (colonne `vwd_identifier_type` incluse).

Les positions sans `vwd_id` ou sans historique sont affichees avec le prix actuel, mais `degiro_indicators` refuse explicitement d'analyser un produit dont `history_ok=False`.

## Why via web

Une fois les 1 a 3 candidats retenus, `web_research` avec une tache par titre (le sub-agent fait son propre `web_search` + `web_fetch` en interne, en parallele des autres titres). Distinguer baisse technique, news sectorielle, deterioration fondamentale.

## Workflow recap par defaut

Le workflow nominal de la skill `market-watch` est le **recap quotidien dual-strategie** sur `core_daily`:

1. `market_watch(strategy="rebound", group="core_daily")` puis `market_watch(strategy="swing", group="core_daily")`. Le cache `degiro_prices` (TTL daily 8 h, invalide en intra-session) rend le 2e appel quasi gratuit.
2. Filtrer **uniquement les `signal == "candidate"`**. Les `recovery`, `reject` et `neutral` sont ignores. Trier par score decroissant, cumuler rebond + swing, garder au plus 5 noms.
3. `web_research` batche sur les noms shortlistes (max 5 taches dans un seul tool_call) pour la lecture news.
4. Le LLM redige une **phrase courte par titre integrant metrics + news**, puis emet un message Telegram a deux sections (`Rebond`, `Swing`). **Pas de section news dediee, pas de shortlist**. Bandeau de fraicheur en tete (`provisoire` ou `settled`). Cible < 1500 caracteres. Toujours utiliser le `label` de la watchlist (= nom d'entreprise), jamais le ticker ou l'ISIN.

Les workflows secondaires (mono-strategie, zoom mono-titre) restent disponibles. Detail dans `skills/market-watch/SKILL.md`.

## Points d'attention

- Toute evolution de la famille `degiro_*` ou de `market_watch` doit aussi mettre a jour `tools.md`, `portefeuille.md`, et les skills `market-watch` / `portfolio-advisor`.
- Toute evolution du format `watchlist.json` doit aussi mettre a jour `workspace-et-memoire.md`.
- Le client vendored doit rester **strip** des methodes d'ordre. Voir `my-agent/vendor/degiro_client/VENDORED.md`.
