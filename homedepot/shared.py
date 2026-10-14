"""Lookups shared by the /homedepot/* endpoint modules: the store a request
prices against (number / link / ZIP -> one store, memoised), the searchModel
call with its sort / price / refinement plumbing, refinement resolution by
facet name, batches of item ids and a thread fan-out."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import config
from homedepot import parsers as P
from homedepot import queries as Q
from homedepot import refs
from homedepot.fetch import HomeDepotNotFound, graphql
from scraper_errors import BadRequest, NotFound, UpstreamError

PAGE_SIZE = 24          # the gateway's cap: a larger pageSize is refused (403)
MAX_PAGE = 100
STORE_TTL = 6 * 3600
ROOT_NAV = "N-5yc1v"    # the site-wide browse root every refinement hangs off
FANOUT_WORKERS = 8

_lock = threading.Lock()
_memo = {}
_fanout = ThreadPoolExecutor(max_workers=FANOUT_WORKERS * 2, thread_name_prefix="homedepot-fanout")


def memo(key, ttl, build):
    now = time.time()
    with _lock:
        hit = _memo.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = build()
    with _lock:
        _memo[key] = (now + ttl, value)
    return value


def run_parallel(fns):
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    futures = [_fanout.submit(fn) for fn in fns[1:]]
    first = fns[0]()
    return [first] + [f.result() for f in futures]


def soft(fn, default=None):
    """Wrap an optional lookup (aisle / bay on a stock check): any upstream
    failure yields `default` instead of failing the endpoint."""
    def run():
        try:
            return fn()
        except (UpstreamError, BadRequest, NotFound):
            return default
    return run


# ---- stores ----------------------------------------------------------------------

def store_search(*, query=None, latitude=None, longitude=None, limit=10, services=None):
    """storeSearch -> {"stores": [parsed], "suggestions": [...]}. A city
    name the locator finds ambiguous answers suggestions instead of
    stores; the first suggestion is then searched by its coordinates."""
    variables = {
        "storeSearchInput": query or "",
        "lat": str(latitude) if latitude is not None else "",
        "lng": str(longitude) if longitude is not None else "",
        "pagesize": str(limit),
        "storeFeaturesFilter": {s: True for s in services} if services else None,
    }
    try:
        data = graphql("storeSearch", Q.STORE_SEARCH, variables, root="storeSearch")
    except UpstreamError as e:
        if "empty reply" in str(e):
            raise HomeDepotNotFound(f"no Home Depot store matches '{query}'")
        raise
    stores = [P.store(s) for s in P.listed(data.get("stores")) if isinstance(s, dict)]
    suggestions = [P.suggested_address(a) for a in P.listed(data.get("suggestedAddresses")) if isinstance(a, dict)]
    if not stores and suggestions and latitude is None:
        first = suggestions[0]
        if first["latitude"] is not None:
            nested = store_search(latitude=first["latitude"], longitude=first["longitude"], limit=limit, services=services)
            nested["searched"] = first
            nested["suggestions"] = suggestions
            return nested
    return {"stores": stores, "suggestions": suggestions, "searched": None}


def stores_near(location, limit=10, services=None):
    """A resolved location ({"zip"} | {"query"} | {"latitude", "longitude"} |
    {"id"}) -> store_search result."""
    if "latitude" in location:
        return store_search(latitude=location["latitude"], longitude=location["longitude"], limit=limit, services=services)
    if "id" in location:
        return store_search(query=location["id"], limit=limit, services=services)
    return store_search(query=location.get("zip") or location.get("query"), limit=limit, services=services)


def store_by_id(store_id):
    """One store by number (memoised)."""
    def build():
        found = store_search(query=refs.plain_store_id(store_id), limit=1)
        stores = found["stores"]
        if not stores or stores[0]["id"] != refs.plain_store_id(store_id):
            raise HomeDepotNotFound(f"store '{store_id}' not found")
        return stores[0]
    return memo(f"store:{refs.plain_store_id(store_id)}", STORE_TTL, build)


def nearest_store(zip_code):
    def build():
        found = store_search(query=zip_code, limit=1)
        if not found["stores"]:
            raise HomeDepotNotFound(f"no Home Depot store near ZIP {zip_code}")
        return found["stores"][0]
    return memo(f"zip:{zip_code}", STORE_TTL, build)


def locate_store(ref):
    """A resolved `store` ref ({"id"} | {"zip"} | None) -> the parsed store
    (the configured default when none was given)."""
    if not ref:
        return store_by_id(config.HOMEDEPOT_DEFAULT_STORE_ID)
    if "zip" in ref:
        return nearest_store(ref["zip"])
    return store_by_id(ref["id"])


def store_context(store):
    """The gateway variables that localise prices / stock to `store`."""
    zip_code = (store.get("address") or {}).get("zip") or config.HOMEDEPOT_DEFAULT_ZIP
    return {"storeId": store["id"], "zipCode": zip_code, "additionalSearchParams": {"deliveryZip": zip_code}}


def store_summary(store):
    address = store.get("address") or {}
    return {"id": store["id"], "name": store["name"], "link": store["link"], "city": address.get("city"),
            "state": address.get("state"), "zip": address.get("zip"), "phone": store.get("phone"),
            "distance_miles": store.get("distance_miles")}


# ---- searchModel ---------------------------------------------------------------------

def search_model(store, *, keyword=None, nav=None, page=1, sort=None, min_price=None, max_price=None,
                 page_size=PAGE_SIZE):
    """One searchModel call -> the raw searchModel object."""
    price_filter = {}
    if min_price is not None or max_price is not None:
        price_filter = {"rangefilter": "price"}
        if min_price is not None:
            price_filter["lowerBound"] = min_price
        if max_price is not None:
            price_filter["upperBound"] = max_price
    variables = dict(store_context(store), keyword=keyword, navParam=nav,
                     startIndex=(page - 1) * page_size, pageSize=page_size,
                     orderBy=sort or {"field": "BEST_MATCH", "order": "ASC"}, filter=price_filter)
    operation = "searchModel"
    return graphql(operation, Q.SEARCH, variables, root="searchModel")


def redirect_nav(raw_search):
    """metadata.searchRedirect ('/b/Tools-Hand-Tools-Hammers/N-5yc1vZc98g?NCNI-5')
    -> its browse code, or None."""
    return refs.category_code(P._dict(P._dict(raw_search).get("metadata")).get("searchRedirect"))


def with_refinements(nav, keys):
    """'N-5yc1vZc27f' + ['zv', '1z175a5'] -> 'N-5yc1vZc27fZzvZ1z175a5'."""
    base = nav or ROOT_NAV
    for key in keys:
        if key and key not in base.split("Z"):
            base += f"Z{key}"
    return base


def refinement_keys(raw_search, wanted):
    """Resolve facet values by name against a searchModel's dimensions.
    `wanted` is [(facet name, value name or predicate)]; returns the keys
    found and the names that matched nothing."""
    dims = {}
    for dim in P.listed(raw_search.get("dimensions")):
        label = (P.text(P._dict(dim).get("label")) or "").lower()
        values = []
        for ref in P.listed(P._dict(dim).get("refinements")):
            ref = P._dict(ref)
            values.append(ref)
            values.extend(P._dict(n) for n in P.listed(ref.get("nestedRefinements")))
        dims.setdefault(label, []).extend(values)
    keys, missing = [], []
    for facet_name, wanted_value in wanted:
        values = dims.get(facet_name.lower(), [])
        match = None
        for ref in values:
            label = P.text(ref.get("label")) or ""
            if callable(wanted_value):
                ok = wanted_value(label)
            else:
                ok = label.lower() == str(wanted_value).lower()
            if ok and P.text(ref.get("refinementKey")):
                match = P.text(ref.get("refinementKey"))
                break
        if match:
            keys.append(match)
        else:
            missing.append(wanted_value if not callable(wanted_value) else facet_name)
    return keys, missing


def min_rating_matcher(minimum):
    """The Review Rating facet lists "5", "4 & Up", "3 & Up", ..."""
    def match(label):
        head = label.split("&")[0].strip()
        return head.isdigit() and int(head) == minimum
    return match


def listing(store, *, keyword=None, nav=None, page=1, sort=None, min_price=None, max_price=None,
            brands=None, min_rating=None, pickup_today=False):
    """A product listing with the facet filters applied. Brand / rating /
    pickup filters are refinement keys on the browse code, so a listing
    that uses them is two calls: one to read the facets, one filtered."""
    wanted = [("brand", b) for b in (brands or [])]
    if min_rating:
        wanted.append(("review rating", min_rating_matcher(min_rating)))
    if pickup_today:
        wanted.append(("get it fast", "Pick Up Today"))
    raw = search_model(store, keyword=keyword, nav=nav, page=page if not wanted else 1, sort=sort,
                       min_price=min_price, max_price=max_price)
    redirect = redirect_nav(raw)
    redirect_link = refs.absolute_link(P._dict(raw.get("metadata")).get("searchRedirect")) if redirect else None
    searched_keyword = keyword
    if redirect and not P.listed(raw.get("products")):
        # The site answers some keywords ("hammer") with a category redirect
        # instead of results: follow it the way the browser does.
        nav, keyword = redirect, None
        raw = search_model(store, nav=nav, page=page if not wanted else 1, sort=sort,
                           min_price=min_price, max_price=max_price)
    unmatched = []
    if wanted:
        keys, unmatched = refinement_keys(raw, wanted)
        if keys:
            raw = search_model(store, keyword=keyword, nav=with_refinements(nav, keys), page=page, sort=sort,
                               min_price=min_price, max_price=max_price)
        elif page > 1:
            raw = search_model(store, keyword=keyword, nav=nav, page=page, sort=sort,
                               min_price=min_price, max_price=max_price)
    parsed = P.search_page(raw)
    if redirect:
        parsed["redirect_link"] = redirect_link
        parsed["query"] = parsed["query"] or searched_keyword
    parsed["unmatched_filters"] = [str(u) for u in unmatched]
    parsed["pagination"] = P.pagination(page, PAGE_SIZE, parsed.pop("total"), max_pages=MAX_PAGE)
    return parsed


# ---- item batches --------------------------------------------------------------------

def items(store, item_ids):
    """searchModel(itemIds) -> parsed cards in the requested order (ids the
    gateway does not know are simply absent)."""
    if not item_ids:
        return []
    variables = dict(store_context(store), itemIds=list(item_ids))
    data = graphql("specialBuyItems", Q.ITEMS, variables, root="searchModel")
    cards = {c["id"]: c for c in (P.product_card(p) for p in P.listed(data.get("products")) if isinstance(p, dict)) if c["id"]}
    return [cards[i] for i in item_ids if i in cards]


def items_batched(store, item_ids, batch=refs.MAX_BULK):
    chunks = [item_ids[i:i + batch] for i in range(0, len(item_ids), batch)]
    results = run_parallel([lambda c=c: items(store, c) for c in chunks])
    return [card for group in results for card in group]


def aisle_bays(store, store_skus):
    if not store_skus:
        return {}
    data = graphql("aislebay", Q.AISLE_BAY, {"storeId": refs.pad_store_id(store["id"]), "storeSkuIds": list(store_skus)},
                   root="aislebay")
    return P.aisle_bay(data)
