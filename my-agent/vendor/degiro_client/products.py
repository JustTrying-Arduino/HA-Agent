"""Product search and lookup by ID."""

from __future__ import annotations

from typing import Any

from . import endpoints as ep
from .http import DegiroHTTP
from .models import Product
from .session import SessionManager


def _to_product(raw: dict[str, Any]) -> Product:
    return Product(
        id=str(raw.get("id")),
        symbol=raw.get("symbol"),
        name=raw.get("name"),
        isin=raw.get("isin"),
        currency=raw.get("currency"),
        vwd_id=raw.get("vwdId"),
        product_type=raw.get("productType"),
        exchange_id=raw.get("exchangeId"),
        raw=raw,
    )


def search(
    http: DegiroHTTP,
    session: SessionManager,
    query: str,
    *,
    limit: int = 10,
    offset: int = 0,
    product_type: int | None = None,
    enrich: bool = True,
) -> list[Product]:
    state = session.require()
    params: dict[str, Any] = {
        "crypto": 1,
        "offset": offset,
        "limit": limit,
        "searchText": query,
        "intAccount": state.int_account,
        "sessionId": state.session_id,
    }
    if product_type is not None:
        params["productTypeId"] = product_type
    resp = http.request("GET", ep.PRODUCTS_LOOKUP_URL, params=params)
    payload = resp.json()
    raw_list = payload if isinstance(payload, list) else payload.get("products", [])
    flat: list[dict[str, Any]] = []
    for item in raw_list:
        if isinstance(item, list):
            flat.extend(x for x in item if isinstance(x, dict))
        elif isinstance(item, dict):
            flat.append(item)
    results = [_to_product(p) for p in flat]

    if enrich:
        missing = [p.id for p in results if not p.vwd_id]
        if missing:
            detailed = get_by_ids(http, session, missing)
            by_id = {p.id: p for p in results}
            for pid, enriched in detailed.items():
                existing = by_id.get(pid)
                if existing and enriched.vwd_id:
                    existing.vwd_id = enriched.vwd_id
                    if not existing.isin:
                        existing.isin = enriched.isin
                    if not existing.currency:
                        existing.currency = enriched.currency
    return results


def get_by_ids(
    http: DegiroHTTP, session: SessionManager, product_ids: list[str]
) -> dict[str, Product]:
    if not product_ids:
        return {}
    state = session.require()
    url = state.product_search_url + ep.PRODUCTS_INFO_PATH
    params = {"intAccount": state.int_account, "sessionId": state.session_id}
    resp = http.request(
        "POST", url, params=params, json=[str(pid) for pid in product_ids]
    )
    data = resp.json().get("data", {})
    return {pid: _to_product(raw) for pid, raw in data.items()}
