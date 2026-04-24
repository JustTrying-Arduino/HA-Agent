# Portefeuille (Degiro)

## Perimetre

L'agent HA lit le portefeuille Degiro de l'utilisateur (positions, cash, P&L jour et cumulatif) via la bibliotheque `degiro_client` vendored dans `my-agent/vendor/degiro_client/`. Il propose des observations cadrees par seuils via le skill `portfolio-advisor`.

**Garde-fou fondamental**: l'agent **ne peut pas passer d'ordre**. Les methodes d'ordre (`place_order`, `check_order`, `confirm_order`, `cancel_order`) sont **physiquement retirees** du client vendored. Meme sous prompt injection, l'appel n'existe pas.

## Authentification

Chaine de config: `my-agent/config.yaml` -> HA options UI -> `/data/options.json` -> `run.sh` -> variables d'environnement -> `cfg` dans `agent/config.py`.

Options HA:
- `degiro_username` (`str?`)
- `degiro_password` (`password?`)
- `degiro_totp_seed` (`password?`, optionnel si 2FA desactivee)

`run.sh` initialise aussi:
- `DEGIRO_DATA_DIR=/data/degiro` (survit aux redemarrages du conteneur).
- `DEGIRO_KEY`: passphrase generee une fois dans `/data/degiro/.key` (droits 600). Sert a chiffrer `credentials.enc` au repos via Fernet + PBKDF2.

### Fingerprint de credentials

`agent/degiro.py` calcule au boot `HMAC-SHA256(DEGIRO_KEY, username|password|totp_seed)` et le compare au fingerprint persiste dans `/data/degiro/.creds_fingerprint`. Si different (l'utilisateur a change son mot de passe dans les options HA), force un `client.login(persist=True)` et reecrit le fingerprint. Evite l'ecueil "session persistee mais creds obsoletes -> relogin silencieux echoue".

### Relogin auto

Le `SessionManager` de `degiro_client` declenche un relogin transparent apres 25 min d'inactivite (ou sur un 401). Aucune intervention cote HA-Agent.

## Tools Degiro

Tous lecture seule, exposes uniquement si les credentials sont configures.

| Tool | Role |
|------|------|
| `degiro_portfolio(include_closed=?)` | Snapshot: positions, cash, P&L jour et cumulatif, cash pseudo-produits (`FLATEX_EUR`). |
| `degiro_search(query, limit=?)` | Resolution produit: ISIN, symbol, exchange_id, currency, vwd_id. |
| `degiro_quote(query)` | Prix courant + variation jour + drawdown vs 52w high + distance au 52w low. Via `price_metadata()`. |
| `degiro_candles(query, window=?, limit=?)` | Serie close-only. Fenetres: `today-10m`, `5d-1h`, `1m-1d`, `3m-1d`, `1y-1d`, `5y-1w`. |
| `degiro_indicators(query, strategy)` | Verdict structure (`candidate` / `reject` / `neutral`) sur une strategie rebound ou swing. |

`market_watch(strategy, group=?)` (famille market) est le screener de la watchlist selon la strategie choisie.

## Limitations close-only

- `price_history()` renvoie **uniquement `close` et `timestamp`**. Aucun `open`, `high`, `low`, `volume`.
- Consequence: pas de confirmations "volume au retournement" ou "volume sur breakout" cote tool.
- Les indicateurs (`agent/indicators.py`) sont tous close-only: RSI(14) Wilder, SMA(N), slope, breakout 20j, support/resistance par clustering de closes, drawdown via `highPriceP1Y` de metadata.
- Pour un breakout douteux: croiser avec `web_search` / `web_fetch`.

## Portefeuille tolerant

`degiro_portfolio` accepte:
- positions sans `isin` ou `vwd_id` (produits exotiques, cash technique);
- lignes `FLATEX_EUR` (cash pseudo-produits retournes par `get_portfolio`) affichees separement;
- positions sans historique exploitable: prix courant affiche, `degiro_indicators` refuse l'analyse technique avec un message clair.

## Skill `portfolio-advisor`

Workspace: `skills/portfolio-advisor/SKILL.md`. Ton **factuel + suggestions cadrees par seuils**:

- concentration > 30 % sur une ligne -> suggerer de reduire;
- drawdown > 20 % sur une ligne vs 52w high -> signaler, proposer analyse technique, pas d'achat;
- exposition devise > 70 % dans une devise non domestique -> signaler risque de change;
- cash > 20 % sans plan d'emploi -> mentionner, sans recommander d'achat.

**Interdictions**:
- pas de recommandation d'achat nominale;
- pas de price target;
- pas d'allocation cible en pourcentage.

Disclaimer systematique en fin de reponse: "Ces observations ne sont pas un conseil en investissement. L'agent ne peut pas passer d'ordre."

## Vendoring

- Code copie depuis `Degiro-API` dans `my-agent/vendor/degiro_client/`.
- Les methodes d'ordre sont retirees a la main dans `client.py` et `orders.py` de la copie vendored.
- `my-agent/vendor/degiro_client/VENDORED.md` documente le commit source, les limitations (close-only, `P1W` -> `P7D`), et la procedure de resync.

## Dependances runtime

Ajoutees dans `my-agent/requirements.txt`:
- `httpx>=0.27`
- `pyotp>=2.9`
- `cryptography>=42`

Dans le `Dockerfile`: `COPY vendor/ /opt/vendor/` et `PYTHONPATH=/opt:/opt/vendor`.

## Points d'attention

- Toute evolution de la famille `degiro_*` ou du skill `portfolio-advisor` doit aussi mettre a jour `tools.md`, `veille-boursiere.md`, et le skill `market-watch` si les indicateurs changent.
- Toute resync du client vendored doit mettre a jour `VENDORED.md` (commit hash) et reverifier que les methodes d'ordre restent retirees.
- Aucun secret (credentials, session_id, user_token) ne doit apparaitre dans les logs.
