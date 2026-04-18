# Veille boursiere

## Perimetre

La V1 de veille boursiere repose sur des donnees `end-of-day` uniquement. Le projet ne vise pas le temps reel ni l'intraday: l'usage cible est la veille, l'alerte et les strategies simples de rebond a partir des clotures.

## Tool natif

Le tool `market_watch` porte l'integration produit:

- il lit une watchlist structuree depuis `workspace/skills/market-watch/watchlist.json`;
- il rafraichit les donnees EOD via Marketstack si necessaire;
- il stocke l'historique localement dans SQLite;
- il renvoie un resume directement exploitable par l'agent: top hausses, top baisses, candidats rebond, falling knives et rappel de quota.

Le tool reste volontairement compact: il ne fait pas lui-meme la recherche du "why". Cette etape est deleguee au tandem `web_search` + `web_fetch` pour ne cibler que les quelques dossiers vraiment interessants.

## Cache et quota

Le cache local vit dans deux tables SQLite:

- `market_eod_prices`: historique EOD par `symbol`, `exchange` et `date`;
- `market_api_usage`: audit local des consommations Marketstack en equivalent "symbol-requests".

Le comportement recherche est:

- ne pas rappeler Marketstack si un symbole a deja ete rafraichi dans la journee et que le cache local est suffisant;
- faire un backfill historique seulement si l'historique local est trop court ou si un refresh force est demande;
- separer les appels par exchange afin de desambiguizer les symboles courts du marche francais (`AI`, `OR`, etc.);
- garder un groupe quotidien restreint car le plan gratuit n'est pas adapte a un full scan quotidien type CAC40 + US.

Hypothese produit retenue: la doc Marketstack indique que chaque symbole dans `symbols=` consomme une requete. L'audit interne suit donc ce modele de quota. C'est une inference de produit a revalider en integration reelle si Marketstack facture differemment sur certains endpoints.

## Watchlist workspace

La watchlist embarquee est un fichier workspace utilisateur, donc editable sans rebuild:

- `skills/market-watch/watchlist.json`

Le fichier fournit:

- `default_group`: groupe utilise par defaut;
- `monthly_symbol_budget`: budget interne plus conservateur que le plafond theorique;
- des groupes de symboles:
  - `core_daily` pour la veille quotidienne;
  - `cac_seed` comme base francaise a elargir et valider;
  - `us_key` pour les grandes actions US.

`cac_seed` est une base pratique, pas une promesse de composition CAC40 officiellement validee ou figee. Les symboles exacts Marketstack et la composition cible doivent rester ajustables dans le fichier.

## Heuristiques de strategie

Le tool classe des signaux simples a partir de l'historique quotidien:

- `capitulation rebound`: forte baisse avec reprise depuis le plus bas du jour;
- `oversold mean reversion`: baisse multi-seances et drawdown marque versus les plus hauts recents;
- `trend pullback`: correction plus propre au sein d'une tendance moins abimee;
- `falling knife`: cloture proche des plus bas et faibles signes d'absorption.

Ces labels sont des heuristiques de tri, pas des recommandations de trading.

## Why via web

Une fois les 1 a 3 cas les plus interessants identifies avec `market_watch`, l'agent peut:

1. lancer `web_search` cible sur le nom de la societe, le ticker et la date recente;
2. lire l'article le plus credible avec `web_fetch`;
3. distinguer baisse technique, news sectorielle et deterioration fondamentale.

Cette separation est importante: un candidat "rebond" technique peut etre invalide par un vrai changement de these.

## Points d'attention

- Si la watchlist contient des titres US, un run apres la cloture parisienne mais avant la cloture US produira naturellement des dates de reference heterogenes.
- Toute evolution de `market_watch` doit aussi mettre a jour `tools.md`.
- Toute evolution de structure de `watchlist.json` doit aussi mettre a jour `workspace-et-memoire.md`.
