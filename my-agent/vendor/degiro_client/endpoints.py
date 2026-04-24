"""Degiro endpoint constants.

Vendored read-only. Order-related endpoints (CHECK_ORDER_PATH, ORDER_PATH,
ORDER_ACTIONS, ORDER_TYPES, TIME_TYPES) are kept as constants but nothing
in this vendored copy calls them.
"""

BASE_URL = "https://trader.degiro.nl/"

LOGIN_PATH = "login/secure/login"
LOGIN_TOTP_PATH = "login/secure/login/totp"
LOGOUT_PATH = "trading/secure/logout"
CONFIG_PATH = "login/secure/config"

ACCOUNT_INFO_PATH = "v5/account/info/"
UPDATE_PATH = "v5/update/"

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
