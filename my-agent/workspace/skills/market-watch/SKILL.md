# Market Watch

## Purpose
Screener watchlist Degiro (rebond/swing, close-only) — utiliser pour veille boursiere, detecter des setups, ou zoomer sur un titre de la watchlist.

## Use This Skill When
- L'utilisateur demande une veille boursiere sur sa watchlist CAC / US.
- L'utilisateur veut identifier des setups de rebond (RSI extreme, support, debut de reprise) ou de swing (tendance haussiere, pullback propre, breakout).
- L'utilisateur veut zoomer sur un titre particulier et lire les indicateurs cles.

## Workflow
1. `market_watch(strategy="rebound")` ou `market_watch(strategy="swing")` pour classer la watchlist (candidats / rejets / neutres).
2. Pour un nom retenu, zoomer avec `degiro_indicators(query=..., strategy=...)` pour voir le detail des signaux et metriques.
3. `degiro_candles(query=..., window=...)` pour lire la serie (close-only), surtout en intraday (`today-10m`).
4. `web_search` puis `web_fetch` pour confirmer le "why" fondamental sur 1 a 3 noms maximum. Preferer Reuters, Bloomberg, FT, WSJ, Les Echos, Boursorama, ou l'entreprise.
5. Conclure explicitement: un rebond technique ne se traite pas comme une cassure fondamentale.

## Strategies

### Rebond
- RSI(14) < 30 (marque "extreme" si < 20).
- Drawdown significatif vs plus haut 1 an (seuil defaut -20 %).
- Close proche d'un niveau de support dense (cluster de cloture).
- Debut de reprise (close > close-1 ou stabilisation sur 2-3 points).
- Rejet automatique "falling knife" si support casse + RSI bas + pente SMA50 negative.

### Swing
- Close > SMA200 **et** SMA50 > SMA200.
- Pullback propre vers la SMA50 (ecart |close - SMA50|/SMA50 <= 3 %) sur fond de pente SMA50 positive.
- Reprise close-only (close aujourd'hui > close veille).
- Breakout close-only: close franchit le plus haut des 20 cloture precedentes.

## Limitations close-only
- Degiro **ne fournit ni volume ni OHL**: aucune confirmation "volume au retournement" ou "volume sur breakout" n'est possible cote tool.
- Toujours signaler cette limite quand l'utilisateur pose une question qui suggere une analyse OHLCV.
- Pour un breakout douteux, croiser avec `web_search` / `web_fetch`.

## Tools utilises
- `market_watch`: screener par strategie sur la watchlist.
- `degiro_indicators`: verdict structure sur un nom.
- `degiro_candles`: serie close-only, supporte `today-10m`, `5d-1h`, `1m-1d`, `3m-1d`, `1y-1d`, `5y-1w`.
- `degiro_quote`: prix courant + variation jour + drawdown 52w.
- `degiro_search`: resolution ISIN / symbol / exchange quand l'utilisateur donne un nom flou.
- `web_search` / `web_fetch`: pour le "why" fondamental.

## Watchlist
- Fichier: `skills/market-watch/watchlist.json`.
- Format **ISIN-first**, chaque entree: `{ "isin": "...", "label": "...", "currency": "EUR", "exchange_id": "..." (optionnel) }`.
- Ajouter `exchange_id` / `currency` en cas de risque d'ambiguite (ADR / listings multiples).
- Groupes disponibles: lire le fichier pour la liste a jour (`default_group`, `core_daily`, `us_key`, ...).

## Output Style
- Structure: resume strategie -> liste des candidats -> rejets -> neutres -> limites close-only.
- Pour chaque candidat: metriques brutes (RSI, SMA50, SMA200, drawdown, support) + pourquoi c'est un setup.
- Rappeler le perimetre: veille et alerte, pas trading intraday automatise, pas de passage d'ordre par l'agent.
