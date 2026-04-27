# Market Watch

## Purpose
Veille boursiere sur la watchlist Degiro (close-only). Workflow par defaut: recap quotidien dual-strategie (rebond + swing) sur le groupe `core_daily`. Cas secondaires: screen mono-strategie, zoom 1 titre.

## Use This Skill When
- "recap", "veille", "core daily", "fais le point" -> workflow recap dual.
- "zoome sur X", "que penses-tu de X" -> workflow mono-titre.
- "rebond cac", "swing us" -> workflow mono-strategie sur un groupe specifique.

## Workflow par defaut: recap dual-strategie
1. `market_watch(strategy="rebound", group="core_daily", max_candidates=8)`.
2. `market_watch(strategy="swing",   group="core_daily", max_candidates=8)`.
3. Construire la shortlist (max 5 noms, ordre de priorite):
   a. candidats sur les **deux** strategies (setup confluent),
   b. top rebond par score decroissant,
   c. top swing par score decroissant.
4. Pour chaque nom shortliste: `degiro_indicators(query=ISIN, strategy=...)` sur la strategie dominante. Recuperer RSI, drawdown, SMA50, SMA200, ecart au support, score.
5. Why web sur **2 noms maximum**: `web_search "<label> news"` puis `web_fetch` sur la source la plus credible (Reuters, Bloomberg, FT, WSJ, Les Echos, Boursorama, site corporate). 1 ligne pour distinguer baisse technique / news / deterioration fondamentale.
6. Sortir au format Telegram (cf. Output).

## Workflows secondaires
- **Mono-strategie**: `market_watch(strategy=..., group=...)` puis `degiro_indicators` sur 1-3 noms retenus.
- **Mono-titre**: `degiro_quote` -> `degiro_indicators` (les 2 strategies) -> `degiro_candles` si lecture intraday demandee -> `web_search`/`web_fetch` si "why".

## Strategies (resume — detail dans `agent/indicators.py`)
### Rebond
RSI(14) < 30, drawdown vs 52w high (-20 % par defaut), proximite cluster support, debut de reprise. Rejet "falling knife": support casse + RSI bas + pente SMA50 negative.
### Swing
Close > SMA200 **et** SMA50 > SMA200, pullback propre vers SMA50 (ecart <= 3 %), reprise close-only, breakout = close > max(20 closes precedents).

## Recommandations a produire
- Rebond seul: "guetter rebond" si support tient et debut de reprise, "attendre confirmation" sinon (close > close-1 sur 2 seances).
- Swing seul: "swing valide" (pullback + reprise), "breakout actif" (close > 20-high), "trend casse" (SMA50 < SMA200).
- Confluent: "setup confluent" — citer les deux signaux.
- Toujours rappeler la limite close-only quand le verdict implique du volume.
- **Jamais** suggerer un ordre. L'agent ne passe pas d'ordre.

## Output Telegram (recap)
Cible < 1500 caracteres. Date au format ISO en heure locale Paris.

```
Recap core daily — <YYYY-MM-DD>

Setups confluents (n):
- TICKER (label) | reco | RSI=.. SMA50=.. DD=-..%
  why: <1 ligne>

Rebond (n):
- TICKER | reco | metriques cles

Swing (n):
- TICKER | reco | metriques cles

Rejets: <noms>

Note close-only.
```

Cas vide: "Rien a signaler aujourd'hui sur core_daily" + eventuels rejets / falling knives.

## Garde-fous
- Maximum **2** appels `web_search` par recap.
- Si `market_watch` echoue (Degiro offline, credentials, etc.): message court explicite, ne rien inventer.

## Limitations close-only
Degiro ne fournit ni volume ni OHL. Pas de confirmation volume sur breakout / retournement. Toujours signaler quand l'analyse touche au volume.

## Tools utilises
`market_watch`, `degiro_indicators`, `degiro_candles`, `degiro_quote`, `degiro_search`, `web_search`, `web_fetch`.

## Watchlist
Fichier: `skills/market-watch/watchlist.json`. Format ISIN-first: `{ "isin": "...", "label": "...", "currency": "EUR", "exchange_id": "..." (optionnel) }`. Ajouter `exchange_id` / `currency` en cas d'ambiguite (ADR, listings multiples). Lire le fichier pour la liste a jour des groupes (`core_daily`, ...).
