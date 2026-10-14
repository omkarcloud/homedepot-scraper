"""Live endpoint smoke tests: one call per /homedepot/* route against a
running service, with example values proven to return data (2026-10-14).
The listing tooling reads each route's FIRST call from this file's AST as
its working example, so the values stay literals.

Skipped unless HOMEDEPOT_BASE points at a running service:

    ONLY_SCRAPER=homedepot python run.py
    HOMEDEPOT_BASE=http://127.0.0.1:6002 python -m pytest homedepot/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("HOMEDEPOT_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set HOMEDEPOT_BASE to run live endpoint tests")


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=240)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def test_search():
    page = call("/homedepot/products/search", query="milwaukee drill")
    assert page["count"] > 1000 and page["next"] and len(page["products"]) == 24
    assert page["products"][0]["pricing"]["currency"] == "USD" and page["products"][0]["rating"]["count"] > 0
    assert page["store"]["id"] == "121" and page["filters"] and page["categories"]
    filtered = call("/homedepot/products/search", query="drill", sort="price_desc", brands="DEWALT,Makita",
                    min_rating=4, pickup_today="true", min_price=100, max_price=400)
    assert 0 < filtered["count"] < page["count"]
    assert {p["brand"] for p in filtered["products"]} <= {"DEWALT", "Makita"}
    # the site's own "Pick Up Today" facet is approximate: a stray 0-qty card slips through
    in_stock = [p["fulfillment"]["pickup"]["is_in_stock"] for p in filtered["products"]]
    assert in_stock.count(True) >= len(in_stock) * 0.8
    assert call("/homedepot/products/search", query="milwaukee drill", page=2)["current_page"] == 2
    local = call("/homedepot/products/search", query="hammer", store="78701")
    assert local["store"]["state"] == "TX" and local["redirect_link"] and local["products"]
    lookup = call("/homedepot/products/lookup", query="3697-22")
    assert lookup["is_exact_match"] and lookup["match"]["id"] == "320326787"
    assert call("/homedepot/products/lookup", query="045242637744")["match"]["model_number"] == "3697-22"


def test_product():
    product = call("/homedepot/products/details", product="320326787")["product"]
    assert product["upc"] == "045242637744" and product["specifications"] and product["images"]
    assert product["fulfillment"]["pickup"]["store"]["id"] == "121" and product["pricing"]["price"] > 100
    link = "https://www.homedepot.com/p/Milwaukee-M18-FUEL-18V-Lithium-Ion-Brushless-Cordless-Hammer-Drill-and-Impact-Driver-Combo-Kit-2-Tool-with-2-Batteries-3697-22/320326787"
    assert call("/homedepot/products/details", product=link)["product"]["id"] == "320326787"
    bulk = call("/homedepot/products/bulk", products="320326787,325403100")
    assert bulk["count"] == 2 and bulk["not_found"] == []
    stock = call("/homedepot/products/availability", product="320326787", location="Austin, TX", limit=3)
    assert stock["count"] == 3 and stock["stores"][0]["state"] == "TX" and "quantity" in stock["stores"][0]
    assert any(s["aisle"] for s in stock["stores"])
    assert call("/homedepot/products/availability", product="320326787")["stores"][0]["id"] == "121"


def test_reviews_and_questions():
    page = call("/homedepot/products/reviews", product="320326787")
    assert page["count"] > 1000 and len(page["reviews"]) == 10 and page["rating"]["distribution"]["5"] > 0
    low = call("/homedepot/products/reviews", product="320326787", sort="lowest_rating", ratings="1,2",
               verified_only="true", page=2)
    assert all(r["rating"] <= 2 and r["is_verified_purchase"] for r in low["reviews"])
    assert call("/homedepot/products/reviews", product="320326787", search="battery", sort="with_photos")["reviews"][0]["photos"]
    questions = call("/homedepot/products/questions", product="320326787", limit=5, sort="oldest")
    assert questions["count"] > 50 and len(questions["questions"]) == 5
    assert any(q["answers"] for q in questions["questions"])
    assert call("/homedepot/products/questions", product="320326787", search="warranty")["count"] > 0


def test_categories():
    departments = call("/homedepot/categories")
    assert departments["count"] >= 15 and any(d["name"] == "Tools" for d in departments["departments"])
    page = call("/homedepot/categories/products", category="N-5yc1vZc27f")
    assert page["count"] > 500 and page["category"]["name"] == "DRILLS" and page["products"] and page["categories"]
    assert [b["name"] for b in page["breadcrumbs"]] == ["Tools", "Power Tools", "Drills"]
    brand = call("/homedepot/categories/products", category="https://www.homedepot.com/b/Milwaukee/N-5yc1vZzv",
                 sort="top_rated", min_rating=4)
    assert brand["count"] > 100 and {p["brand"] for p in brand["products"]} == {"Milwaukee"}


def test_stores():
    found = call("/homedepot/stores/search", location="30339")
    assert found["count"] == 10 and found["stores"][0]["id"] == "121" and found["stores"][0]["hours"]
    city = call("/homedepot/stores/search", location="Austin, TX", limit=3, services="tool_rental")
    assert city["count"] == 3 and city["searched"]["name"] == "Austin, TX"
    assert all(s["services"]["tool_rental"] for s in city["stores"])
    assert call("/homedepot/stores/search", location="40.7128,-74.0060", limit=2)["stores"][0]["address"]["state"] == "NY"
    assert call("/homedepot/stores/details", store="121")["store"]["name"] == "Cumberland"
    assert call("/homedepot/stores/details", store="78701")["store"]["address"]["state"] == "TX"


def test_deals():
    deals = call("/homedepot/deals")
    assert deals["count"] > 20 and deals["ends_at"] and deals["groups"][0]["products"][0]["pricing"]["price"]


def test_errors():
    # paths via variables so the listing tooling never reads an error case
    # as a route's working example
    details, search, store = "/homedepot/products/details", "/homedepot/products/search", "/homedepot/stores/details"
    category, stores = "/homedepot/categories/products", "/homedepot/stores/search"
    call(details, status=404, product="999999999")
    call(details, status=400, product="https://www.lowes.com/pd/1")
    call(search, status=400)
    call(search, status=400, query="drill", sort="cheapest")
    call(search, status=400, query="drill", foo="bar")
    call(category, status=404, category="N-5yc1vZzzzzzz")
    call(store, status=404, store="9999")
    call(stores, status=404, location="zzqqxx")
