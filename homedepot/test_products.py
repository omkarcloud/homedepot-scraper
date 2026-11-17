"""Offline tests for /homedepot/products/* handlers (homedepot/products.py):
a store SKU given where the item id is expected, and stock checks whose
store reads fail. The gateway is stubbed with the 2026-10-14 fixtures; no
box, no network.

    python -m pytest homedepot/test_products.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from homedepot import parsers as P  # noqa: E402
from homedepot import products, shared  # noqa: E402
from homedepot.fetch import (HomeDepotBadRequest, HomeDepotBlocked, HomeDepotNotFound,  # noqa: E402
                             HomeDepotUpstreamError)

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
ITEM, SKU = "320326787", "1007850144"          # the same drill kit: internet number and store SKU
STORES = [{"id": "121", "name": "Cumberland", "link": "l/121", "address": {"zip": "30339"}},
          {"id": "128", "name": "Buckhead", "link": "l/128", "address": {"zip": "30324"}}]


def fx(name):
    with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def gateway(monkeypatch):
    """The gateway knows ITEM (and the search finds it by SKU); `calls`
    records what was asked; `failing` is a set of store ids whose stock read
    raises `error`."""
    calls, failing = [], set()
    state = {"error": HomeDepotUpstreamError("specialBuyItems: browser box unavailable")}
    card = next(c for c in (P.product_card(p) for p in fx("items")["products"]) if c["id"] == ITEM)

    def graphql(operation, query, variables, root=None):
        calls.append((operation, variables.get("itemId")))
        if variables.get("itemId") != ITEM:
            raise HomeDepotNotFound(f"Item not found: {variables.get('itemId')}")
        return fx("product")

    def search_model(store, *, keyword=None, **kw):
        calls.append(("searchModel", keyword))
        return fx("lookup_model") if keyword == SKU else fx("search_empty")

    def stock_at(store, item_id):
        calls.append(("stock", store["id"], item_id))
        if store["id"] in failing:
            raise state["error"]
        return dict(card) if item_id == ITEM else None

    monkeypatch.setattr(products, "graphql", graphql)
    monkeypatch.setattr(shared, "search_model", search_model)
    monkeypatch.setattr(products, "_stock_at", stock_at)
    monkeypatch.setattr(shared, "locate_store", lambda ref: STORES[0])
    monkeypatch.setattr(shared, "stores_near", lambda location, limit=10, services=None: {"stores": list(STORES), "searched": None})
    monkeypatch.setattr(shared, "aisle_bays", lambda store, skus: {})
    return calls, failing, state


def test_details_by_item_id_costs_one_call(gateway):
    calls, _, _ = gateway
    assert products.details(ITEM)["product"]["id"] == ITEM
    assert calls == [("productClientOnlyProduct", ITEM)]


def test_details_by_store_sku_resolves_to_the_item(gateway):
    calls, _, _ = gateway
    out = products.details(SKU)["product"]
    assert out["id"] == ITEM and out["store"]["id"] == "121"
    assert calls == [("productClientOnlyProduct", SKU), ("searchModel", SKU), ("productClientOnlyProduct", ITEM)]


def test_details_of_an_unknown_number_is_still_not_found(gateway):
    with pytest.raises(HomeDepotNotFound, match="999999999"):
        products.details("999999999")


def test_availability_by_store_sku_resolves_to_the_item(gateway):
    calls, _, _ = gateway
    out = products.availability(SKU)
    assert out["product"]["id"] == ITEM and out["product"]["store_sku"] == SKU and out["count"] == 2
    assert ("searchModel", SKU) in calls and ("stock", "128", ITEM) in calls


def test_availability_of_an_unknown_number_is_not_found(gateway):
    with pytest.raises(HomeDepotNotFound, match="999999999"):
        products.availability("999999999")


def test_one_store_failing_leaves_the_others(gateway):
    _, failing, _ = gateway
    failing.add("128")
    out = products.availability(ITEM)
    assert [s["id"] for s in out["stores"]] == ["121", "128"]
    assert out["stores"][0]["price"] is not None and out["stores"][1]["quantity"] is None


def test_every_store_failing_is_an_upstream_error_not_a_404(gateway):
    # 2026-11-11: a customer got "product not found" for products that exist
    # while the egress was being refused.
    calls, failing, state = gateway
    failing.update({"121", "128"})
    with pytest.raises(HomeDepotUpstreamError, match="browser box unavailable"):
        products.availability(ITEM)
    assert ("searchModel", ITEM) not in calls                  # no SKU lookup on top of a failing gateway
    state["error"] = HomeDepotBlocked("Akamai refused the request")
    with pytest.raises(HomeDepotBlocked):
        products.availability(ITEM)


def test_a_store_read_answered_not_found_is_a_store_without_the_item(gateway):
    # The gateway's own "not found" on a store read is that store's answer,
    # not the endpoint's: the other stores and the SKU lookup still count.
    calls, failing, state = gateway
    state["error"] = HomeDepotNotFound("Record Not Found")
    failing.add("128")
    out = products.availability(ITEM)
    assert out["stores"][0]["price"] is not None and out["stores"][1]["quantity"] is None
    failing.add("121")
    with pytest.raises(HomeDepotNotFound, match="999999999"):
        products.availability("999999999")
    assert ("searchModel", "999999999") in calls


def test_a_rejected_sku_search_leaves_the_products_own_not_found(gateway, monkeypatch):
    def rejected(store, *, keyword=None, **kw):
        raise HomeDepotBadRequest("the gateway refused this searchModel request (HTTP 403)")
    monkeypatch.setattr(shared, "search_model", rejected)
    with pytest.raises(HomeDepotNotFound, match="999999999"):
        products.details("999999999")
    with pytest.raises(HomeDepotNotFound, match="999999999"):
        products.availability("999999999")
