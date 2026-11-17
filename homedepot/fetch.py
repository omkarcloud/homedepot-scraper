"""Home Depot transport: every request is an in-page fetch() inside a headed
Chrome page parked on homedepot.com — on the browser box (recipes/homedepot.py)
since 2026-10-22, through browser_client. No plain-HTTP path, no chrome pool
(homedepot is in config.POOLLESS_FLAGS), no browser in this process.

Every page of homedepot.com is built from ONE endpoint:

    POST https://apionline.homedepot.com/federation-gateway/graphql?opname=<op>

(search / browse = searchModel, product page = productClientOnlyProduct,
reviews, questionsAnswers, storeSearch, aislebay, savingsDepartment,
specialBuyMetadata — the documents live in homedepot/queries.py). The
gateway is fronted by Akamai Bot Manager. Why a browser, validated live
2026-10-14:

  * Plain curl_cffi with no cookies, the homepage's cookies, or through a
    US residential exit answers HTTP 206 {"data":{"Generic Errors API":null}}
    on every operation; every www page except the homepage is a 403.
  * Replaying the Akamai cookies (_abck / bm_sz / bm_s / bm_so) of a headed
    browser over curl_cffi passed from a home connection, but NEVER from
    the GKE pod: cookies minted direct or through sticky residential exits,
    every chrome124…chrome150 target, the full cookie jar — all 206, from
    the same egress IP the browser used.
  * The same browser's own in-page fetch of the same call answers 200 from
    the pod, even when its _abck never validates.

THE SPLIT (Phase 5 of the browser migration, 2026-10-22). The box keeps
parked, Akamai-validated pages: its warm loads the homepage, gives the sensor
pointer activity until `_abck` validates, proves the page with a tiny
storeSearch probe and parks it on /robots.txt; every gateway POST is an
in-page fetch on such a page (0.3-1 s); a 206/401 refusal fails the lease so
the next call relaunches. This module keeps the GraphQL layer: the operation
headers, the retry loop, the error taxonomy and the EGRESS.

THE EGRESS (rewritten 2026-11-12). Akamai judges the egress IP as well as
the page, so the box is told which egress to use per call:

  * HOME: config.homedepot_proxy() (None = the box's OWN IP). Every call
    goes here while Akamai accepts it, on config.HOMEDEPOT_BROWSER_SLOTS
    pages of that one egress (the first keyed by the egress, the others by a
    session id). A proven page answers in under a second, so callers queue
    behind the pages instead of opening more.
  * FALLBACK: fresh sticky exits from config.homedepot_fallback_proxy(),
    used ONLY while the home egress is being skipped: after the box reports
    Akamai refusing a fresh home page (its warm-up), for
    config.HOMEDEPOT_DIRECT_SKIP seconds. A refused exit is replaced.

Until 2026-11-12 the home egress and the fallback exits were offered together
as interchangeable candidates (1 home page + up to 7 exits). The box opens a
new browser whenever every open one is busy, so any second concurrent call
launched a cold browser on a residential exit: 12-25 s per warm-up, and
Akamai refuses most exits (homepage 403 / probe 206), each refusal moving on
to the next exit. Measured from the pod that day: 6 concurrent product reads
took 34 s with 3 refused exits, while the one home page answered in 0.4 s;
with two home pages 12 concurrent reads finish in under 8 s. The ledger for
Nov 4-12 had 252 502s on this API, 167 of them the box's 20 s queue timeout
behind such warm-ups, and single calls that ran for up to 288 s walking
refused exits. Hence also REQUEST_BUDGET: one request never runs longer.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  HomeDepotUpstreamError  box unavailable, fetch failure, 5xx, GraphQL errors — retryable
  HomeDepotBlocked        Akamai refused every egress tried                   — retryable later
  HomeDepotBadRequest     the gateway rejected the arguments                  — never retried
  HomeDepotNotFound       entity does not exist                               — never retried

Run this file directly for a smoke test against the box (BROWSER_BOX_URLS):
    python homedepot/fetch.py
"""
import json
import fastjson
import os
import sys
import threading
import time
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_client
import config
from browser_client import BoxRefused, BoxUnavailable
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from scraper_utils import debug

SITE = "https://www.homedepot.com"
GATEWAY = "https://apionline.homedepot.com/federation-gateway/graphql"
MAX_ATTEMPTS = 3            # box calls per request that the gateway answered badly (5xx)
MAX_REFUSALS = 5            # refusals (a dropped page, a refused exit) one request rides out on top of those
REQUEST_BUDGET = 75         # seconds one request may take in all: a refused warm-up costs 12-25 s
MIN_CALL_SECONDS = 20       # no further box call with less of the budget left (a cold page takes 10-15 s)

# x-experience-name / x-current-url the site sends per page type; the gateway
# does not enforce them, but the pairs below are the ones observed.
EXPERIENCES = {
    "searchModel": ("search-desktop", "/s/"),
    "specialBuyItems": ("general-merchandise", "/daily-deals"),
    "productClientOnlyProduct": ("general-merchandise", "/p/"),
    "savingsDepartment": ("general-merchandise", "/daily-deals"),
    "aislebay": ("general-merchandise", "/p/"),
    "reviews": ("general-merchandise", "/p/"),
    "questionsAnswers": ("general-merchandise", "/p/"),
    "storeSearch": ("store-locator", "/l/store-locator"),
    "specialBuyMetadata": ("general-merchandise", "/daily-deals"),
}


class HomeDepotUpstreamError(UpstreamError):
    """Box unavailable, fetch failure, 5xx or a GraphQL error — retryable."""


class HomeDepotBlocked(HomeDepotUpstreamError, Blocked):
    """Akamai refused every egress tried (206 / 401) — retryable later."""


class HomeDepotBadRequest(BadRequest):
    """The gateway rejected the arguments — never retried."""


class HomeDepotNotFound(NotFound):
    """Entity does not exist — never retried."""


def dump_debug(name, text):
    debug.dump("HOMEDEPOT_DEBUG_DIR", name, text, encoding="utf-8")


# ---- the egress ---------------------------------------------------------------------
# HOME pages while Akamai accepts the home egress, FALLBACK exits while it is
# being skipped (see the module docstring). The box keys a parked page by the
# session id when one is sent, else by the proxy URL ("direct" for None), so
# the same candidates on every call reuse the same proven pages.
_UNSET = object()
_lock = threading.Lock()
_home = _UNSET               # the home egress, held so a configured exit stays one sticky URL
_home_skip_until = 0.0       # monotonic: Akamai refused the home egress, use the fallback exits until then
PAGE_ONLY = ("page dropped", "in-page fetch failed")   # refusals of one page (recipes/homedepot.py fetch_one)


def _slots():
    return max(1, int(config.HOMEDEPOT_BROWSER_SLOTS or 1))


def _home_egress():
    global _home
    with _lock:
        if _home is _UNSET:
            _home = config.homedepot_proxy()
        return _home


def _home_candidates():
    """The home pages, [(proxy, session)]: the first keyed by the egress
    itself (the page every pod has always used), the rest by a session id.
    The session id of a configured exit names that exit (its port, as the
    box's own key does): the box keys such a page by the session alone, so a
    plain "page-2" kept serving on the OLD exit after the home exit was
    replaced, for as long as that browser lived."""
    home = _home_egress()
    tag = f"p{urlsplit(home).port}-" if home else ""
    return [(home, None)] + [(home, f"{tag}page-{i}") for i in range(2, _slots() + 1)]


def _on_home():
    """Home unless Akamai refused it recently and there are exits to use instead."""
    return time.monotonic() >= _home_skip_until or not config.HOMEDEPOT_FALLBACK_PROXY_COUNTRY


def _skip_home(refused):
    """Akamai refused the home egress `refused`: the fallback exits serve for
    HOMEDEPOT_DIRECT_SKIP seconds, then home is proven again on a fresh page.
    A configured exit is replaced by a new one for that. A refusal of an exit
    that was replaced meanwhile (two calls failing on one exit, the second
    reporting late) says nothing about the new one: it is left alone."""
    global _home, _home_skip_until
    with _lock:
        if _home is not _UNSET and _home != refused:
            return
        if _home is not None:
            _home = _UNSET
        _home_skip_until = time.monotonic() + config.HOMEDEPOT_DIRECT_SKIP


def _egress_label(proxy):
    return f"exit port {urlsplit(proxy).port}" if proxy else "direct egress"


# The share only (no burst): the box opens a browser whenever every open one
# is busy, and a new exit is a cold, often refused warm-up; two proven exits
# serve a queue faster than a third being opened.
_FALLBACK = browser_client.ExitPool("homedepot", lambda: config.homedepot_fallback_proxy(), size=_slots)


# ---- one call ----------------------------------------------------------------------

def _headers_for(operation):
    experience, current = EXPERIENCES.get(operation, ("general-merchandise", "/"))
    return {"content-type": "application/json", "accept": "*/*", "x-experience-name": experience,
            "x-current-url": current, "x-hd-dc": "origin", "x-api-cookies": "{}", "x-debug": "false"}


def _fetch_box(operation, payload, timeout):
    """One gateway POST as an in-page fetch on one of the box's parked pages
    (the box picks among the home pages, or among the fallback exits while
    home is skipped) -> (on the home egress?, the egress used, status, body
    text). Raises BoxRefused / BoxUnavailable carrying `.on_home` and
    `.proxy`, the egress it happened on."""
    on_home = _on_home()
    call = dict(url=f"{GATEWAY}?opname={operation}", method="POST", headers=_headers_for(operation),
                body=json.dumps(payload), timeout=timeout)
    try:
        if on_home:
            candidates = _home_candidates()
            index, res = browser_client.fetch_any("homedepot", candidates, **call)
            proxy = candidates[index][0]
        else:
            proxy, res = _FALLBACK.fetch_any("homedepot", **call)
    except (BoxRefused, BoxUnavailable) as e:
        e.on_home = on_home
        raise
    return on_home, proxy, int(res.get("status") or 0), res.get("body") or ""


def _graphql_errors(body):
    errors = body.get("errors") if isinstance(body, dict) else None
    if isinstance(errors, list) and errors:
        return [e.get("message") for e in errors if isinstance(e, dict)]
    return []


def _looks_like_not_found(message):
    """"ItemId: 999999999 not found", "Record Not Found" (a parent id that
    is not a product)."""
    return "not found" in (message or "").lower()


def _looks_like_bad_input(message):
    low = (message or "").lower()
    return any(token in low for token in ("invalid", "must be", "not a valid", "bad request"))


def _value_of(operation, body, root):
    """A parsed gateway reply -> `data` (or `data[root]`), or the mapped error."""
    data = body.get("data") if isinstance(body, dict) else None
    errors = _graphql_errors(body)
    value = data.get(root) if (root and isinstance(data, dict)) else data
    if value is None:
        message = "; ".join(m for m in errors if m) or "empty reply"
        if any("ValidationError" in (m or "") or "Validation error" in (m or "") for m in errors):
            raise HomeDepotUpstreamError(f"{operation}: the gateway rejected the document: {message}")
        if errors and any(_looks_like_not_found(m) for m in errors):
            raise HomeDepotNotFound(message)
        if errors and any(_looks_like_bad_input(m) for m in errors):
            raise HomeDepotBadRequest(message)
        raise HomeDepotUpstreamError(f"{operation}: {message}")
    return value


def _is_refusal(status, text):
    """Akamai's verdicts: 206 with the "Generic Errors API" body, or a 401."""
    return status in (206, 401) or (status != 200 and "Generic Errors" in (text or ""))


def graphql(operation, query, variables, *, root=None):
    """POST one operation through one of the box's parked homedepot.com
    pages; return the `data` member (or `data[root]`).

    A refusal is ridden out, within MAX_REFUSALS and REQUEST_BUDGET seconds:
    a page Akamai dropped mid-call is replaced by the box on the same egress
    (a parked page goes stale; the fresh page's warm-up is what judges the
    egress), a refused home egress hands over to the fallback exits, a
    refused exit is replaced. A box that is down or busy is an upstream
    error at once. GraphQL errors with no usable data raise
    HomeDepotUpstreamError (a validation error names the field, so a schema
    change is visible in the message)."""
    payload = {"operationName": operation, "variables": variables, "query": query}
    deadline = time.monotonic() + REQUEST_BUDGET
    last = None
    attempts = refusals = home_drops = 0
    while attempts < MAX_ATTEMPTS and refusals < MAX_REFUSALS:
        remaining = deadline - time.monotonic()
        if (attempts or refusals) and remaining < MIN_CALL_SECONDS:
            break
        try:
            on_home, proxy, status, text = _fetch_box(operation, payload, max(MIN_CALL_SECONDS, int(remaining)))
        except BoxRefused as e:
            if e.candidate is None:
                # the box refused before any browser was reached (a bad
                # request, an unknown variant): no egress is to blame
                raise HomeDepotUpstreamError(f"{operation}: browser box refused the request: {e}")
            refusals += 1
            last = HomeDepotBlocked(f"Akamai refused the request: {e}")
            page_only = any(mark in str(e) for mark in PAGE_ONLY)
            if not e.on_home:
                print(f"homedepot: {operation} refused via {_egress_label(e.proxy)} ({e}); replacing that exit")
                _FALLBACK.rotate(e.proxy)
            elif page_only and ("in-page fetch failed" in str(e) or home_drops < _slots()):
                # one page's trouble (a wedged Chrome, a parked page gone
                # stale): the box closed it and opens a fresh one on the same
                # egress, whose warm-up is the verdict on the egress. More
                # drops than there are parked pages means fresh pages are
                # dropped too: that is the egress.
                home_drops += "page dropped" in str(e)
                print(f"homedepot: {operation} lost its page on {_egress_label(e.proxy)} ({e}); retrying on a fresh one")
            else:
                print(f"homedepot: {operation} refused on {_egress_label(e.proxy)} ({e}); "
                      f"fallback exits for {config.HOMEDEPOT_DIRECT_SKIP}s")
                _skip_home(e.proxy)
            continue
        except BoxUnavailable as e:
            raise HomeDepotUpstreamError(f"{operation}: browser box unavailable: {e}")
        if _is_refusal(status, text):
            # the recipe raises on these itself; a verdict that still got
            # through left its page parked, so the egress moves on
            dump_debug(f"refused_{operation}", text)
            print(f"homedepot: {operation} refused (HTTP {status}) via {_egress_label(proxy)}, moving the egress on")
            refusals += 1
            last = HomeDepotBlocked(f"Akamai refused the request (HTTP {status})")
            if on_home:
                _skip_home(proxy)
            else:
                _FALLBACK.rotate(proxy)
            continue
        if status == 403:
            # A 403 is a rule on the request itself (seen for searchModel
            # pageSize > 24), never the page's verdict (that is the 206).
            dump_debug(f"forbidden_{operation}", text)
            raise HomeDepotBadRequest(f"the gateway refused this {operation} request (HTTP 403)")
        if status >= 500:
            attempts += 1
            last = HomeDepotUpstreamError(f"{operation}: HTTP {status}")
            time.sleep(config.RETRY_BACKOFF * attempts)
            continue
        if status != 200:
            raise HomeDepotUpstreamError(f"{operation}: HTTP {status}: {text[:200]}")
        try:
            body = fastjson.loads(text)
        except Exception:
            dump_debug(f"nonjson_{operation}", text)
            raise HomeDepotUpstreamError(f"{operation}: non-JSON reply")
        return _value_of(operation, body, root)
    raise last or HomeDepotUpstreamError(f"{operation}: no attempt succeeded")


if __name__ == "__main__":
    # Smoke test against the box: a store lookup, a search and a product
    # read through its parked page.
    from homedepot import queries as Q
    started = time.monotonic()
    stores = graphql("storeSearch", Q.STORE_SEARCH,
                     {"storeSearchInput": "30339", "pagesize": "3", "lat": "", "lng": ""},
                     root="storeSearch")
    print(f"stores near 30339 ({time.monotonic() - started:.1f}s):",
          [(s["storeId"], s["name"]) for s in stores["stores"]])
    started = time.monotonic()
    search = graphql("searchModel", Q.SEARCH, {
        "keyword": "milwaukee drill", "navParam": None, "storeId": "121", "zipCode": "30339",
        "startIndex": 0, "pageSize": 5, "orderBy": {"field": "BEST_MATCH", "order": "ASC"},
        "filter": {}, "additionalSearchParams": {"deliveryZip": "30339"}}, root="searchModel")
    print(f"search ({time.monotonic() - started:.1f}s): {search['searchReport']['totalProducts']} products;",
          [p["identifiers"]["productLabel"][:40] for p in search["products"]][:3])
    started = time.monotonic()
    product = graphql("productClientOnlyProduct", Q.PRODUCT,
                      {"itemId": "320326787", "storeId": "121", "zipCode": "30339"}, root="product")
    print(f"product ({time.monotonic() - started:.1f}s):", product["identifiers"]["productLabel"],
          product["pricing"]["value"])
