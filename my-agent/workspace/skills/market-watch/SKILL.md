# Market Watch

## Purpose
Veille boursiere sur la watchlist Degiro (close-only). Workflow par defaut: recap quotidien dual-strategie (rebond + swing) sur le groupe `core_daily`. Cas secondaires: screen mono-strategie, zoom 1 titre.

## Use This Skill When
- "recap", "veille", "core daily", "fais le point" -> workflow recap dual.
- "zoome sur X", "que penses-tu de X" -> workflow mono-titre.
- "rebond cac", "swing us" -> workflow mono-strategie sur un groupe specifique.

## Workflow par defaut: recap dual-strategie
1. `market_watch(strategy="rebound", group="core_daily")` puis `market_watch(strategy="swing", group="core_daily")`.
2. Filtrer **uniquement les `signal == "candidate"`**. Les `recovery` (rebond deja avance) ne remontent pas dans le recap. Les `reject` / `neutral` non plus.
3. Trier les candidates restants par score decroissant. Cumuler rebond + swing. Si > 5 noms cumules, **garder les 5 meilleurs scores cumules**.
4. **Pour chaque candidate** retenu, batcher un seul appel `web_research` avec une tache par titre (max 5 taches dans le tool_call), `question="news recentes affectant <label> sur la derniere semaine"`, `hint="ticker=<ISIN>, contexte: rebond/swing technique"`. Sources prioritaires Reuters, Bloomberg, FT, WSJ, Les Echos, Boursorama, site corporate.
5. Rediger une **phrase courte par titre** integrant **metrics + news**: ex. *"Airbus — proche support a -1.2%, RSI 28, debut de reprise mesuree ; news : guidance 2026 maintenue malgre livraisons en retard."* Phrase < 200 caracteres.
6. Sortir au format Telegram (cf. Output). Si aucune candidate sur les deux strategies: message court "Rien a signaler aujourd'hui sur core_daily. Donnees arretees au <ts>."

## Workflows secondaires
- **Mono-strategie**: `market_watch(strategy=..., group=...)` puis `degiro_indicators` sur 1-3 noms retenus.
- **Mono-titre**: `degiro_quote` -> `degiro_indicators` (les 2 strategies) -> `degiro_candles` si lecture intraday demandee -> `web_search`/`web_fetch` si "why".

## Strategies (resume — detail dans `agent/indicators.py`)
### Rebond
RSI(14) ≤ 35 (gate strict, sinon `neutral`), drawdown vs 52w high (-20% par defaut), proximite cluster support, debut de reprise mesuree (var_1d entre +0.3% et +2%). Filtre anti-rattrapage: si var_3d > +4% -> signal `recovery` (deja parti, pas a entrer). Rejet "falling knife": support casse + RSI bas + pente SMA50 negative.
### Swing
Close > SMA200 **et** SMA50 > SMA200, pullback propre vers SMA50 (ecart ≤ 3%), reprise close-only, breakout = close > max(20 closes precedents).

## Fraicheur des donnees
- Le tool greffe automatiquement la derniere bougie intraday comme **bougie provisoire** quand le close du jour n'est pas encore settled (Euronext < 18h05, NYSE/NASDAQ < 22h30 Paris) ou que la cache n'a pas encore aujourd'hui.
- La sortie tool inclut `bar_ts` et `provisional=True/False` par titre, et un bandeau `Freshness: last_bar_max=... | provisional=N/M`.
- Cas **provisoire**: signaler dans le bandeau Telegram (`provisoire`). Cas **settled**: marquer `settled`.

## Output Telegram (recap)
Cible **< 1500 caracteres**. Date au format ISO + heure locale Paris dans le bandeau.

```
<b>Recap core_daily</b> — <YYYY-MM-DD HH:MM> (<provisoire|settled>)

<b>Rebond</b> (n)
- <b>Airbus</b> — <phrase analyse + news inline>
- <b>Saint-Gobain</b> — <phrase analyse + news inline>

<b>Swing</b> (n)
- <b>Veolia</b> — <phrase analyse + news inline>
- <b>Engie</b> — <phrase analyse + news inline>

<i>Close-only Degiro. Pas de confirmation volume.</i>
```

**Regles strictes du format**:
- Toujours utiliser le `label` (= nom d'entreprise) du watchlist. **Pas de ticker, pas d'ISIN** dans le message.
- Section omise entierement si vide (pas de `Rebond (0)`).
- **Pas de section "Lecture news"** dediee, **pas de "Shortlist"** finale. La news est inline dans la phrase de chaque titre.
- Phrases courtes, 1 ligne par titre, < 200 caracteres.
- Bandeau de tete: `<provisoire>` si au moins 1 titre est en bougie provisoire, sinon `<settled>`.
- **Jamais** suggerer un ordre. L'agent ne passe pas d'ordre.

## Garde-fous
- Maximum **5** taches dans le batch `web_research` par recap (une par titre shortliste).
- Si `market_watch` echoue (Degiro offline, credentials, etc.): message court explicite, ne rien inventer.

## Limitations close-only
Degiro ne fournit ni volume ni OHL. Pas de confirmation volume sur breakout / retournement. Toujours signaler quand l'analyse touche au volume.

## Tools utilises
`market_watch`, `degiro_indicators`, `degiro_candles`, `degiro_quote`, `degiro_search`, `web_research`.

## Watchlist
Fichier: `skills/market-watch/watchlist.json`. Format ISIN-first: `{ "isin": "...", "label": "...", "currency": "EUR", "exchange_id": "..." (optionnel) }`. Ajouter `exchange_id` / `currency` en cas d'ambiguite (ADR, listings multiples). Lire le fichier pour la liste a jour des groupes (`core_daily`, ...).
