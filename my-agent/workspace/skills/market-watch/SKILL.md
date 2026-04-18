# Market Watch

## Purpose
Analyse les hausses et baisses d'une watchlist actions en end-of-day, repere les grosses baisses exploitables en strategie de rebond, et complete le "why" par une recherche web ciblee seulement sur les cas les plus pertinents.

## Use This Skill When
- L'utilisateur demande une veille boursiere quotidienne ou ponctuelle sur une watchlist CAC / US.
- L'utilisateur veut identifier des baisses fortes, drawdowns et signaux simples de rebond.
- L'utilisateur veut comprendre rapidement pourquoi une action a baisse avant de qualifier une strategie.

## Workflow
- Commencer par `market_watch` pour rafraichir le cache Marketstack et obtenir un tri des hausses, baisses, candidats rebond et falling knives.
- Utiliser par defaut le groupe `core_daily` pour tenir les quotas. N'elargir a des groupes plus gros que si l'utilisateur le demande ou si le plan Marketstack le permet.
- Si `market_watch` remonte 1 a 3 vrais candidats, lancer ensuite `web_search` sur ces seuls noms pour chercher le "why" de la baisse.
- Lire les articles les plus credibles avec `web_fetch` avant de conclure. Preferer Reuters, Bloomberg, Financial Times, WSJ, Les Echos, Boursorama ou la societe elle-meme.
- Si la baisse vient d'un resultat, warning, guidance, downgrade, litigation, M&A, secteur ou macro, le dire explicitement: un rebond technique ne se traite pas pareil qu'une cassure fondamentale.

## Strategy Lens
- `capitulation rebound`: grosse baisse jour J, reprise depuis le plus bas, parfois volume eleve. C'est un setup de rebond court terme, pas une these long terme.
- `oversold mean reversion`: plusieurs seances de baisse et drawdown marque contre le plus haut recent. A verifier contre la cause fondamentale.
- `trend pullback`: repli dans une tendance encore correcte. Generalement plus propre qu'un couteau qui tombe.
- `falling knife`: cloture proche des plus bas, peu de reprise, drawdown deja profond. A eviter tant que le why n'est pas clarifie.

## Quota Discipline
- Marketstack gratuit est trop serre pour un balayage quotidien "full CAC + US" si chaque symbole compte contre le quota.
- Le cache SQLite local existe pour eviter de reconsommer l'API sans raison.
- Le fichier `watchlist.json` embarque un groupe `core_daily` et des groupes plus larges. Adapter ce fichier avant d'augmenter la frequence.
- Pour une veille quotidienne melangeant Paris et US, programmer le run apres la cloture US si l'on veut un snapshot homogene. Sinon assumer que les titres US peuvent avoir un jour de retard.

## Files
- Lire si besoin `skills/market-watch/watchlist.json` pour voir les groupes disponibles et ajuster la watchlist.
- Le cache de prix et l'audit de quota vivent dans SQLite, pas dans le workspace.

## Output Style
- Repondre en priorite avec: top baisses, top hausses, candidats rebond, risques a eviter.
- Pour chaque candidat rebond retenu, distinguer clairement les faits de marche, le why issu du web, puis la conclusion strategique prudente.
- Rappeler que ce skill sert a la veille et a l'alerte EOD, pas au trading intraday.
