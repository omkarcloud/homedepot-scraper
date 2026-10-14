"""Offline tests: ref parsing, the request schemas and the normalizers
against raw federation-gateway replies captured 2026-10-14
(homedepot/fixtures/*.json).

    python -m pytest homedepot/test_parsers.py -q
"""
import json
import os

import pytest

from schema_fields import load_query
from homedepot import parsers as P
from homedepot import refs
from homedepot import schemas as S
from homedepot import shared

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fx(name):
    with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def _no_camel_or_url_keys(obj, path="$"):
    """Every emitted key is snake_case and no key is named *url*."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key == key.lower() and " " not in key, f"{path}.{key} not snake_case"
            assert "url" not in key, f"{path}.{key} should be a *link"
            _no_camel_or_url_keys(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_camel_or_url_keys(value, f"{path}[{i}]")


def _no_empty_strings(obj, path="$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            _no_empty_strings(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_empty_strings(value, f"{path}[{i}]")
    else:
        assert obj != "", f"{path} is an empty string (must be null)"


# ---- refs -----------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("320326787", "320326787"), (" 320326787 ", "320326787"),
    ("https://www.homedepot.com/p/Milwaukee-M18-FUEL-3697-22/320326787", "320326787"),
    ("homedepot.com/p/x/320326787", "320326787"),
    ("https://www.homedepot.com/pep/Milwaukee-x/320326787?x=1", "320326787"),
])
def test_resolve_product(value, expected):
    assert refs.resolve_product(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "3697-22", "https://www.lowes.com/pd/1",
                                   "https://www.homedepot.com/b/Tools/N-5yc1vZc1xy"])
def test_resolve_product_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_product(value)


def test_resolve_products():
    assert refs.resolve_products("320326787, https://www.homedepot.com/p/x/325403100,320326787") == [
        "320326787", "325403100"]
    with pytest.raises(ValueError):
        refs.resolve_products(",".join(str(100000000 + n) for n in range(26)))


@pytest.mark.parametrize("value, expected", [
    ("N-5yc1vZc27f", "N-5yc1vZc27f"),
    ("https://www.homedepot.com/b/Tools-Power-Tools-Drills/N-5yc1vZc27f", "N-5yc1vZc27f"),
    ("https://www.homedepot.com/b/Milwaukee/N-5yc1vZzv?NCNI-5", "N-5yc1vZzv"),
    ("https://www.homedepot.com/b/Tools/Best-Rated/N-5yc1vZc298Zbwo5q/Ntk-elasticplus/Ntt-drill", "N-5yc1vZc298Zbwo5q"),
])
def test_resolve_category(value, expected):
    assert refs.resolve_category(value) == expected


@pytest.mark.parametrize("value", ["", "drills", "https://www.homedepot.com/p/x/320326787",
                                   "https://www.lowes.com/pl/N-123"])
def test_resolve_category_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_category(value)


@pytest.mark.parametrize("value, expected", [
    ("121", {"id": "121"}), ("0121", {"id": "121"}),
    ("https://www.homedepot.com/l/Cumberland/GA/Atlanta/30339/121", {"id": "121"}),
    ("30339", {"zip": "30339"}),
])
def test_resolve_store(value, expected):
    assert refs.resolve_store(value) == expected


@pytest.mark.parametrize("value", ["", "Atlanta", "123456", "https://www.homedepot.com/p/x/320326787"])
def test_resolve_store_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_store(value)


@pytest.mark.parametrize("value, expected", [
    ("30339", {"zip": "30339"}),
    ("Austin, TX", {"query": "Austin, TX"}),
    ("33.86,-84.47", {"latitude": 33.86, "longitude": -84.47}),
    ("121", {"id": "121"}),
    ("https://www.homedepot.com/l/Cumberland/GA/Atlanta/30339/121", {"id": "121"}),
])
def test_resolve_location(value, expected):
    assert refs.resolve_location(value) == expected


def test_resolve_location_rejects():
    for value in ("", "x", "123456789", "95,200"):
        with pytest.raises(ValueError):
            refs.resolve_location(value)


def test_links_and_ids():
    assert refs.image_link("https://images.thdstatic.com/x-64_<SIZE>.jpg") == "https://images.thdstatic.com/x-64_1000.jpg"
    assert refs.category_code("/b/Tools/N-5yc1vZc1xy") == "N-5yc1vZc1xy"
    assert refs.category_code(None) is None
    assert refs.pad_store_id("121") == "0121" and refs.plain_store_id("0121") == "121"
    assert shared.with_refinements(None, ["zv", "1z175a5"]) == "N-5yc1vZzvZ1z175a5"
    assert shared.with_refinements("N-5yc1vZc27fZzv", ["zv"]) == "N-5yc1vZc27fZzv"
    assert shared.with_refinements("N-5yc1vZzvq", ["zv"]) == "N-5yc1vZzvqZzv"     # "zv" is not a prefix match


# ---- schemas ----------------------------------------------------------------------------

def test_search_schema():
    data, error = load_query(S.SearchSchema, {"query": " milwaukee  drill ", "sort": "Price_Desc", "min_price": "100",
                                              "brands": "DEWALT, makita", "min_rating": "4", "pickup_today": "yes",
                                              "store": "30339", "page": "2"})
    assert error is None
    assert data["query"] == "milwaukee drill" and data["sort"] == {"field": "PRICE", "order": "DESC"}
    assert data["min_price"] == 100.0 and data["max_price"] is None
    assert data["brands"] == ["DEWALT", "makita"] and data["min_rating"] == 4 and data["pickup_today"] is True
    assert data["store"] == {"zip": "30339"} and data["page"] == 2
    assert load_query(S.SearchSchema, {"query": "x", "sort": "cheapest"})[1]
    assert load_query(S.SearchSchema, {"query": "x", "min_rating": "6"})[1]
    assert load_query(S.SearchSchema, {"query": "x", "foo": "1"})[1]
    assert load_query(S.SearchSchema, {})[1]


def test_other_schemas():
    data, error = load_query(S.ReviewsSchema, {"product": "320326787", "ratings": "5,4", "verified_only": "1",
                                               "sort": "with_photos", "search": "battery"})
    assert error is None and data["ratings"] == ["5", "4"] and data["sort"] == "photoreview" and data["verified_only"] is True
    assert load_query(S.ReviewsSchema, {"product": "320326787", "ratings": "6"})[1]
    data, error = load_query(S.StoreSearchSchema, {"location": "Austin, TX", "services": "tool_rental,Propane", "limit": "3"})
    assert error is None and data["services"] == ["toolRental", "propane"] and data["limit"] == 3
    assert load_query(S.StoreSearchSchema, {"location": "30339", "limit": "41"})[1]
    assert load_query(S.StoreSchema, {})[1]
    data, error = load_query(S.ProductsSchema, {"products": "320326787,325403100"})
    assert error is None and data["products"] == ["320326787", "325403100"] and data["store"] is None
    data, error = load_query(S.AvailabilitySchema, {"product": "320326787"})
    assert error is None and data["location"] is None and data["limit"] == 5
    data, error = load_query(S.CategoryProductsSchema, {"category": "https://www.homedepot.com/b/Milwaukee/N-5yc1vZzv"})
    assert error is None and data["category"] == "N-5yc1vZzv"


# ---- search / browse ------------------------------------------------------------------------

def test_search_page():
    page = P.search_page(fx("search"))
    _no_camel_or_url_keys(page)
    _no_empty_strings(page)
    assert page["query"] == "milwaukee drill" and page["total"] == 2652 and len(page["products"]) == 24
    assert page["store"] == {"id": "121", "name": "Cumberland", "zip": "30339"}
    assert page["in_store_count"] == 287
    assert [b["name"] for b in page["breadcrumbs"]] == ["Tools", "Power Tools"]
    assert page["breadcrumbs"][0]["code"] == "N-5yc1vZc1xy"
    assert page["categories"][0]["name"] == "Power Tools" and page["categories"][0]["code"] == "N-5yc1vZc298"
    assert "milwaukee m12 drill" in page["related_searches"]
    brand = next(f for f in page["filters"] if f["name"] == "Brand")
    assert brand["values"][0]["name"] == "Milwaukee" and brand["values"][0]["key"] == "zv" and brand["values"][0]["count"] > 0
    product = next(p for p in page["products"] if p["id"] == "320326787")
    assert product["model_number"] == "3697-22" and product["store_sku"] == "1007850144"
    assert product["link"].startswith("https://www.homedepot.com/p/") and product["image"].endswith("_1000.jpg")
    assert product["rating"] == {"average": 4.77, "count": 4093}
    assert product["pricing"]["currency"] == "USD" and product["pricing"]["price"] == 399.0
    assert product["pricing"]["conditional_promotions"][0]["tags"] == ["BOGO"]
    assert product["badges"] == ["Top Rated", "Exclusive"]
    assert product["fulfillment"]["pickup"]["store"]["id"] == "121" and product["fulfillment"]["pickup"]["is_in_stock"] is True
    assert product["fulfillment"]["delivery"]["is_available"] is True
    assert product["categories"] == ["Tools", "Power Tools", "Power Tool Combo Kits"]
    assert product["has_variants"] is True and product["quantity_limit"] == 3 and product["return_policy"] == "90-Day"


def test_search_filtered_and_browse():
    page = P.search_page(fx("search_filtered"))
    assert page["applied_filters"][0]["name"] == "Price" and page["applied_filters"][0]["values"][0]["name"] == "$100 - $300"
    browse = P.search_page(fx("browse_category"))
    assert browse["title"] == "DRILLS" and [b["name"] for b in browse["breadcrumbs"]] == ["Tools", "Power Tools", "Drills"]
    assert browse["total"] == 955
    redirect = P.search_page(fx("search_redirect"))
    assert redirect["redirect_link"].endswith("/N-5yc1vZc98g?NCNI-5") and redirect["products"] == []
    assert shared.redirect_nav(fx("search_redirect")) == "N-5yc1vZc98g"
    assert shared.redirect_nav(fx("search")) is None


def test_refinement_keys():
    raw = fx("search")
    keys, missing = shared.refinement_keys(raw, [("brand", "makita"), ("brand", "Nope"),
                                                 ("review rating", shared.min_rating_matcher(4)),
                                                 ("get it fast", "Pick Up Today")])
    assert keys == ["yg", "bwo5o", "1z175a5"] and missing == ["Nope"]


def test_pagination():
    assert P.pagination(2, 24, 100) == {"page": 2, "items_per_page": 24, "total_pages": 5, "total_count": 100}
    assert P.pagination(1, 24, 5000, max_pages=100)["total_pages"] == 100
    assert P.pagination(1, 10, 0)["total_pages"] == 0


# ---- product --------------------------------------------------------------------------------

def test_product_details():
    product = P.product_details(fx("product"))
    _no_camel_or_url_keys(product)
    _no_empty_strings(product)
    assert product["id"] == "320326787" and product["upc"] == "045242637744" and product["gtin"] == "0045242637744"
    assert product["parent_id"] == "342940787" and product["brand_link"] == "https://www.homedepot.com/b/Milwaukee/N-5yc1vZzv"
    assert product["description"].startswith("The MILWAUKEE")
    assert len(product["images"]) == 14 and product["images"][0]["type"] == "primary"
    assert len(product["videos"]) == 2 and product["videos"][0]["uploaded_at"] == "2022-07-03T06:46:19Z"
    assert [g["group"] for g in product["specifications"]] == ["Details", "Warranty / Certifications"]
    assert {"name": "Battery Voltage (V)", "value": "18V"} in product["specifications"][0]["specs"]
    assert product["key_features"][0]["name"] == "Motor Type" and product["key_features"][0]["link"].startswith("https://")
    assert [b["name"] for b in product["breadcrumbs"]] == ["Tools", "Power Tools", "Power Tool Combo Kits"]
    assert product["protection_plan_skus"] == ["343105821", "315046851"]
    assert product["bundle"]["parent_ids"] == ["329611105", "329611073"]
    assert product["prop65"] == {"has_warning": False, "message": None}
    assert product["fulfillment"]["pickup"]["quantity"] == 73 or product["fulfillment"]["pickup"]["quantity"] > 0
    assert product["pricing"]["price"] == 399.0 and product["seo"]["description"]


def test_ship_to_store_is_not_shelf_stock():
    raw = {"fulfillmentOptions": [
        {"type": "pickup", "fulfillable": True, "services": [{"type": "boss", "locations": [
            {"isAnchor": True, "locationId": "6616", "type": "store", "inventory": {"quantity": 534, "isInStock": True}}]}]},
        {"type": "delivery", "fulfillable": True, "services": [{"type": "sth", "locations": [
            {"isAnchor": True, "locationId": "8119", "type": "online", "inventory": {"quantity": 534, "isInStock": True}}]}]}]}
    out = P.fulfillment(raw)
    assert out["pickup"]["quantity"] == 0 and out["pickup"]["is_in_stock"] is False
    assert out["pickup"]["is_available"] is False and out["pickup"]["is_ship_to_store_available"] is True
    assert out["pickup"]["store"]["id"] == "6616" and out["delivery"]["online_quantity"] == 534


def test_items_and_inventory():
    items = [P.product_card(p) for p in fx("items")["products"]]
    assert [i["id"] for i in items] == ["320326787", "325403100"]
    aisles = P.aisle_bay(fx("aislebay"))
    assert aisles == {"1007850144": {"aisle": "15", "bay": "8", "label": "Aisle 15 - Bay 8"}}


# ---- reviews / questions ----------------------------------------------------------------------

def test_reviews():
    raw = fx("reviews")
    rows = [P.review(r) for r in raw["Results"]]
    _no_camel_or_url_keys(rows)
    _no_empty_strings(rows)
    assert len(rows) == 10 and rows[0]["rating"] == 5 and rows[0]["submitted_at"] == "2026-10-13T09:40:29Z"
    assert rows[0]["is_verified_purchase"] is True and rows[0]["badges"] == ["verified_purchaser"]
    assert rows[0]["is_syndicated"] is True and rows[0]["syndication_source"]["name"] == "homedepot.ca"
    with_secondary = next(r for r in rows if r["secondary_ratings"])
    assert with_secondary["secondary_ratings"]["quality"] == 1.0
    stats = P.review_statistics(raw)
    assert stats["average"] == 4.8 and stats["count"] == 4096 and stats["distribution"]["5"] == 3644
    assert stats["recommended_percent"] == 95.5 and stats["secondary_rating_names"] == ["quality", "value"]
    filtered = [P.review(r) for r in fx("reviews_filtered")["Results"]]
    assert all(r["rating"] == 5 and r["is_verified_purchase"] for r in filtered)


def test_questions():
    page = P.questions_page(fx("questions"))
    _no_camel_or_url_keys(page)
    _no_empty_strings(page)
    assert page["total"] == 143 and len(page["questions"]) == 10
    answered = next(q for q in page["questions"] if q["answers"])
    assert answered["answer_count"] >= 1 and answered["answers"][0]["is_brand_answer"] is True
    assert answered["answers"][0]["author"] == "Milwaukee Tool" and answered["asked_at"].endswith("Z")


# ---- stores / deals / departments ---------------------------------------------------------------

def test_stores():
    stores = [P.store(s) for s in fx("stores")["stores"]]
    _no_camel_or_url_keys(stores)
    _no_empty_strings(stores)
    first = stores[0]
    assert first["id"] == "121" and first["number"] == "0121" and first["name"] == "Cumberland"
    assert first["link"] == "https://www.homedepot.com/l/Cumberland/GA/Atlanta/30339/121"
    assert first["address"]["zip"] == "30339" and first["latitude"] == 33.862126 and first["distance_miles"] == 1.27
    assert first["hours"]["sunday"] == {"opens_at": "8:00", "closes_at": "20:00"}
    assert first["services"]["tool_rental"] is True and first["services"]["appliance_showroom"] is False
    by_number = [P.store(s) for s in fx("store_by_number")["stores"]]
    assert by_number[0]["id"] == "121"


def test_departments_and_deals():
    departments = [P.department(d) for d in fx("departments")["departmentCategories"]]
    assert departments[0] == {
        "name": "Appliances", "code": "N-5yc1vZbv1w", "link": "https://www.homedepot.com/b/N-5yc1vZbv1w",
        "deals_code": "N-5yc1vZbv1wZ7",
        "deals_link": "https://www.homedepot.com/b/Appliances/Special-Values/N-5yc1vZbv1wZ7",
        "image": "https://www.homedepot.com/hdus/en_US/DTCCOMNEW/fetch/Global_Assets/SBOTD-Appliances-Savings.jpg"}
    groups = [P.deal_group(g) for g in fx("deals_day")["categoryMetadata"]]
    assert groups[0]["name"] == "New Featured Deals" and len(groups[0]["item_ids"]) == 28
    assert groups[0]["image"].endswith("_1000.jpg")


# ---- helpers ------------------------------------------------------------------------------------

def test_value_helpers():
    assert P.iso_utc("2026-10-13T09:40:29.000+00:00") == "2026-10-13T09:40:29Z"
    assert P.iso_utc("2022-07-03T06:46:19.938Z") == "2022-07-03T06:46:19Z"
    assert P.iso_date("2026-10-14") == "2026-10-14" and P.iso_date("10/14/2026") == "2026-10-14"
    assert P.snake("TOP_SELLERS") == "top_sellers" and P.snake("expandedFlooringShowroom") == "expanded_flooring_showroom"
    assert P.money("12.345") == 12.35 and P.positive(0) is None and P.to_int("4093") == 4093
    assert P.split_csv("AK,GU,HI") == ["AK", "GU", "HI"] and P.split_csv(None) == []
    assert P.pricing({"value": 10, "original": 10})["original_price"] is None
    discounted = P.pricing({"value": 80, "original": 100})
    assert discounted["discount_amount"] == 20.0 and discounted["discount_percent"] == 20.0
    assert P.product_card({})["id"] is None and P.review({})["rating"] is None and P.store({})["id"] is None
