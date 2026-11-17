"""/homedepot/products/* — keyword search with filters, model / UPC / SKU
lookup, full product records, batches, stock at nearby stores with the
aisle and bay, paged reviews with the rating statistics, and questions with
their answers."""
import config
from homedepot import parsers as P
from homedepot import queries as Q
from homedepot import refs
from homedepot import shared
from homedepot.fetch import HomeDepotNotFound, graphql
from scraper_errors import BadRequest, NotFound, UpstreamError

REVIEW_PAGE_SIZE = 10     # the gateway serves 10 reviews per page whatever pagesize says


def _store(store_ref):
    store = shared.locate_store(store_ref)
    return store, shared.store_summary(store)


# ---- search / lookup ----------------------------------------------------------------

def search(query, page=1, sort=None, min_price=None, max_price=None, brands=None, min_rating=None,
           pickup_today=False, store=None):
    located, summary = _store(store)
    page_data = shared.listing(located, keyword=query, page=page, sort=sort, min_price=min_price,
                               max_price=max_price, brands=brands, min_rating=min_rating, pickup_today=pickup_today)
    page_data["store"] = summary
    return page_data


def lookup(query, store=None):
    """A model number (3697-22), UPC / GTIN (045242637744), store SKU
    (1007850144) or internet number typed into the search: the gateway
    answers the matching product(s) first."""
    located, summary = _store(store)
    raw = shared.search_model(located, keyword=query, page=1)
    parsed = P.search_page(raw)
    needle = query.strip().lower()
    exact = [p for p in parsed["products"]
             if needle in {(p.get("model_number") or "").lower(), (p.get("store_sku") or "").lower(), (p.get("id") or "").lower()}]
    if not exact and parsed["total"] == 1 and parsed["products"]:
        exact = parsed["products"][:1]     # a UPC / GTIN resolves to its one product
    return {
        "query": query,
        "store": summary,
        "total": parsed["total"],
        "match": exact[0] if exact else (parsed["products"][0] if parsed["products"] else None),
        "is_exact_match": bool(exact),
        "products": parsed["products"],
    }


# ---- one product / batches -------------------------------------------------------------

def _item_for_sku(store, ref):
    """The item id behind a store SKU (1007850144, the number on the shelf
    tag), or None. `details` and `availability` read by item id (the internet
    number); a customer who keys their products by the SKU got "not found"
    for items that exist (2026-11-11). Asked only after the gateway did not
    know `ref` as an item id, so an item id costs no extra call. A search
    the gateway rejects resolves nothing: the caller's own "not found" stands
    (not a 400 about a search the customer never asked for)."""
    try:
        parsed = P.search_page(shared.search_model(store, keyword=ref, page=1))
    except (BadRequest, NotFound):
        return None
    return next((p["id"] for p in parsed["products"] if p.get("id") and (p.get("store_sku") or "") == ref), None)


def _read_product(located, item_id):
    variables = {"itemId": item_id, "storeId": located["id"],
                 "zipCode": shared.store_context(located)["zipCode"]}
    raw = graphql("productClientOnlyProduct", Q.PRODUCT, variables, root="product")
    parsed = P.product_details(raw)
    if not parsed.get("id"):
        raise HomeDepotNotFound(f"product '{item_id}' not found")
    return parsed


def details(product, store=None):
    located, summary = _store(store)
    try:
        parsed = _read_product(located, product)
    except HomeDepotNotFound:
        item_id = _item_for_sku(located, product)
        if not item_id:
            raise
        parsed = _read_product(located, item_id)
    parsed["store"] = summary
    return {"product": parsed}


def bulk(products, store=None):
    located, summary = _store(store)
    cards = shared.items(located, products)
    found = {c["id"] for c in cards}
    return {"store": summary, "count": len(cards), "not_found": [p for p in products if p not in found],
            "products": cards}


# ---- stock -----------------------------------------------------------------------------

def _stock_at(store, item_id):
    cards = shared.items(store, [item_id])
    return cards[0] if cards else None


def _stock_at_each(stores, item_id):
    """The item's card at each store, None where a store does not list it or
    its read failed. One store failing must not fail the endpoint; EVERY
    store failing is an upstream failure, not "product not found" (until
    2026-11-12 it was answered as a 404, e.g. while Akamai refused the
    egress). A store read the gateway answers "not found" / rejects is a
    store that does not list the item (as shared.soft had it), never the
    endpoint's own error: the SKU lookup still has to run after it."""
    def read(store):
        try:
            return _stock_at(store, item_id)
        except UpstreamError as e:
            return e
        except (BadRequest, NotFound):
            return None
    results = shared.run_parallel([lambda s=s: read(s) for s in stores])
    failures = [r for r in results if isinstance(r, UpstreamError)]
    if failures and len(failures) == len(results):
        raise failures[0]
    return [None if isinstance(r, UpstreamError) else r for r in results]


def availability(product, location=None, limit=5):
    """Stock of one product at the stores nearest `location` (default: the
    configured store's ZIP), with the aisle / bay in each store."""
    if location is None:
        anchor = shared.locate_store(None)
        found = shared.stores_near({"zip": (anchor.get("address") or {}).get("zip") or config.HOMEDEPOT_DEFAULT_ZIP}, limit=limit)
    else:
        found = shared.stores_near(location, limit=limit)
    stores = found["stores"][:limit]
    if not stores:
        raise HomeDepotNotFound("no Home Depot store near that location")
    cards = _stock_at_each(stores, product)
    if all(c is None for c in cards):
        item_id = _item_for_sku(stores[0], product)      # a store SKU instead of the item id
        if not item_id:
            raise HomeDepotNotFound(f"product '{product}' not found")
        cards = _stock_at_each(stores, item_id)
        if all(c is None for c in cards):
            raise HomeDepotNotFound(f"product '{product}' not found")
    sku = next((c.get("store_sku") for c in cards if c and c.get("store_sku")), None)
    aisles = shared.run_parallel([shared.soft(lambda s=s: shared.aisle_bays(s, [sku]), default={}) for s in stores]) \
        if sku else [{} for _ in stores]
    rows = []
    for store, card, aisle in zip(stores, cards, aisles):
        pickup = (card or {}).get("fulfillment", {}).get("pickup", {}) if card else {}
        location_info = (aisle or {}).get(sku) or {}
        rows.append({
            **shared.store_summary(store),
            "quantity": pickup.get("quantity"),
            "is_in_stock": pickup.get("is_in_stock"),
            "is_limited_quantity": pickup.get("is_limited_quantity"),
            "is_pickup_available": pickup.get("is_available"),
            "is_ship_to_store_available": pickup.get("is_ship_to_store_available"),
            "has_curbside_pickup": pickup.get("has_curbside_pickup"),
            "price": ((card or {}).get("pricing") or {}).get("price"),
            "aisle": location_info.get("aisle"),
            "bay": location_info.get("bay"),
            "shelf_location": location_info.get("label"),
        })
    first = next(c for c in cards if c)
    return {
        "product": {"id": first["id"], "name": first["name"], "link": first["link"], "brand": first["brand"],
                    "model_number": first["model_number"], "store_sku": first["store_sku"], "image": first["image"],
                    "currency": P.CURRENCY},
        "searched": found.get("searched"),
        "delivery": first["fulfillment"]["delivery"],
        "count": len(rows),
        "stores": rows,
    }


# ---- reviews / questions -----------------------------------------------------------------

def _review_filters(ratings, verified_only):
    stars = "[%s]" % ", ".join(str(int(r)) for r in ratings) if ratings else "null"
    return "{isVerifiedPurchase: %s, prosCons: null, starRatings: %s}" % ("true" if verified_only else "false", stars)


def reviews(product, page=1, sort="mosthelpfull", ratings=None, verified_only=False, search=None):
    variables = {"itemId": product, "startIndex": (page - 1) * REVIEW_PAGE_SIZE + 1,
                 "pagesize": str(REVIEW_PAGE_SIZE), "sortBy": sort, "searchTerm": search}
    raw = graphql("reviews", Q.reviews(_review_filters(ratings, verified_only)), variables, root="reviews")
    total = P.to_int(raw.get("TotalResults")) or 0
    rows = [P.review(r) for r in P.listed(raw.get("Results")) if isinstance(r, dict)]
    stats = P.review_statistics(raw)
    if not rows and page == 1 and not (stats and stats.get("count")) and not (ratings or verified_only or search):
        # the gateway answers an empty, zero-count page for unknown items
        # (a filtered page that matches nothing is a legitimate empty 200)
        raise HomeDepotNotFound(f"no reviews for product '{product}' (unknown item or none yet)")
    return {
        "product_id": product,
        "rating": stats,
        "reviews": rows,
        "pagination": P.pagination(page, REVIEW_PAGE_SIZE, total),
    }


def questions(product, page=1, limit=10, sort="newest", search=None):
    variables = {"itemId": product, "startindex": (page - 1) * limit + 1, "pagesize": limit,
                 "sortBy": sort, "searchTerm": search or ""}
    raw = graphql("questionsAnswers", Q.QUESTIONS, variables, root="questionsAnswers")
    parsed = P.questions_page(raw)
    return {
        "product_id": product,
        "questions": parsed["questions"],
        "pagination": P.pagination(page, limit, parsed["total"]),
    }
