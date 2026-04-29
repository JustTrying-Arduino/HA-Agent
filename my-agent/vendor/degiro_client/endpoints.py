"""Degiro endpoint constants.

Values sourced from github.com/icastillejogomez/degiro-api (src/enums/DeGiroEnums.ts).
The dynamic URLs (tradingUrl, paUrl, productSearchUrl) are returned by
GET /login/secure/config after login - we don't hardcode them here.
"""

BASE_URL = "https://trader.degiro.nl/"

LOGIN_PATH = "login/secure/login"
LOGIN_TOTP_PATH = "login/secure/login/totp"
LOGOUT_PATH = "trading/secure/logout"
CONFIG_PATH = "login/secure/config"

ACCOUNT_INFO_PATH = "v5/account/info/"
UPDATE_PATH = "v5/update/"
CHECK_ORDER_PATH = "v5/checkOrder"
ORDER_PATH = "v5/order/"

PRODUCTS_LOOKUP_PATH = "v5/products/lookup"
PRODUCTS_INFO_PATH = "v5/products/info"

PRODUCTS_LOOKUP_URL = "https://trader.degiro.nl/productsearch/secure/v2/lookup"

CLIENT_INFO_PATH = "client"

VWD_CHART_URL = "https://charting.vwdservices.com/hchart/v1/deGiro/data.js"

REFERER = "https://trader.degiro.nl/trader/"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

ORDER_ACTIONS = {"BUY": "BUY", "SELL": "SELL"}
ORDER_TYPES = {"LIMITED": 0, "STOP_LIMITED": 1, "MARKET": 2, "STOP_LOSS": 3}
TIME_TYPES = {"DAY": 1, "PERMANENT": 3}

PRODUCT_TYPES = {
    "shares": 1,
    "bonds": 2,
    "futures": 7,
    "options": 8,
    "investmentFunds": 13,
    "leveragedProducts": 14,
    "etfs": 131,
    "cfds": 535,
    "warrants": 536,
}
