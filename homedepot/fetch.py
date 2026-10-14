"""Home Depot transport: every request is an in-page fetch() inside a headed
patchright Chrome page parked on homedepot.com. No plain-HTTP path, no chrome
pool (homedepot is in config.POOLLESS_FLAGS) — the pages are this module's own.

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

So every gateway POST runs inside a real page: a small pool of
config.HOMEDEPOT_BROWSER_PAGES headed pages (one Chrome each), opened lazily
on the homepage (a little pointer activity lets Akamai's sensor post), each
serving one request at a time. A page is replaced when Akamai refuses it,
when its fetch fails or wedges, and once it is older than
config.HOMEDEPOT_BROWSER_MAX_AGE. Akamai also judges the egress IP: the GKE
pod's own IP was later refused even for in-page fetches with a validated
_abck, while some residential exits pass. So a new page proves itself with
one tiny gateway call before it serves traffic; a page that fails is
dropped and the next egress tried — config.homedepot_proxy() (direct by
default), then fresh sticky exits from config.homedepot_fallback_proxy().
A direct egress that fails its probe is skipped for
config.HOMEDEPOT_DIRECT_SKIP seconds.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  HomeDepotUpstreamError  page / fetch failure, 5xx, GraphQL errors — retryable
  HomeDepotBlocked        Akamai refused every page tried              — retryable later
  HomeDepotBadRequest     the gateway rejected the arguments            — never retried
  HomeDepotNotFound       entity does not exist                         — never retried

Run this file directly for a smoke test:
    python homedepot/fetch.py
"""
import json
import os
import queue
import sys
import threading
import time
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

SITE = "https://www.homedepot.com"
GATEWAY = "https://apionline.homedepot.com/federation-gateway/graphql"
TIMEOUT = 45                # seconds per in-page fetch
MAX_ATTEMPTS = 3            # pages tried per request
ACQUIRE_TIMEOUT = 120       # seconds a request waits for a free page
OPEN_ATTEMPTS = 8           # egresses tried to open one page (configured, then fallback exits)
SENSOR_ROUNDS = 8           # pointer rounds waiting for Akamai to validate a new page's _abck
SENSOR_INTERVAL = 1.5       # seconds between rounds
PROBE_ATTEMPTS = 5          # test calls a new page gets before it is judged refused
PROBE_INTERVAL = 2.5        # seconds between them
PROBE_QUERY = ("query storeSearch($storeSearchInput: String, $pagesize: String) "
               "{ storeSearch(storeSearchInput: $storeSearchInput, pagesize: $pagesize) { stores { storeId } } }")
PAGE_BLOCK_RESOURCES = ("image", "font", "media")
PAGE_BLOCK_HOSTS = (
    "collector-pxj770cp7y.px-cloud.net", "c.go-mpulse.net", "*.akstat.io",
    "www.google-analytics.com", "*.doubleclick.net", "*.googletagmanager.com",
    "*.adobedc.net", "*.demdex.net", "*.quantummetric.com", "*.forter.com",
    "*.bazaarvoice.com", "*.qualtrics.com", "*.paypal.com", "*.segment.io",
    "*.cquotient.com", "*.liveperson.net", "*.lpsnmedia.net",
)

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
    """Page / fetch failure, 5xx or a GraphQL error — retryable."""


class HomeDepotBusy(HomeDepotUpstreamError):
    """Every page stayed busy for ACQUIRE_TIMEOUT — asking again only queues."""


class HomeDepotBlocked(HomeDepotUpstreamError, Blocked):
    """Akamai refused every page tried (206 / 401) — retryable later."""


class HomeDepotBadRequest(BadRequest):
    """The gateway rejected the arguments — never retried."""


class HomeDepotNotFound(NotFound):
    """Entity does not exist — never retried."""


def dump_debug(name, text):
    dbg = os.environ.get("HOMEDEPOT_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


# ---- pages ----------------------------------------------------------------------
# A slot is one page (one headed Chrome). Free slots wait in a queue, so a
# request holds a page for exactly one fetch and concurrent requests spread
# over the pool; slots are created lazily up to HOMEDEPOT_BROWSER_PAGES.
_free = queue.Queue()
_slots_lock = threading.Lock()
_slot_count = 0
_direct_skip_until = 0.0     # monotonic: skip the configured egress after it failed a probe


def _proxy_candidates():
    """Egresses a page open tries in order: the configured one (direct by
    default) unless it recently failed its probe, then fresh fallback exits."""
    out = []
    if time.monotonic() >= _direct_skip_until:
        out.append(config.homedepot_proxy())
    for _ in range(OPEN_ATTEMPTS - len(out)):
        fallback = config.homedepot_fallback_proxy()
        if fallback:
            out.append(fallback)
    return out or [config.homedepot_proxy()]


def _wiggle(page, step):
    """A little pointer + scroll activity for Akamai's sensor."""
    page.mouse.move(180 + step * 23, 260 + step * 7)
    page.mouse.move(420 + step * 5, 340 + step * 11, steps=10)
    page.mouse.wheel(0, 260)


def _open_page_once(proxy):
    from chrome_manager import create_scope
    from patchright_driver import PatchrightDriver

    label = f"exit port {urlsplit(proxy).port}" if proxy else "direct egress"
    print(f"homedepot: opening a page via headed patchright ({label})...")
    with create_scope():
        driver = PatchrightDriver(proxy_url=proxy, headless=False, geoip_timezone=bool(proxy),
                                  block_resources=PAGE_BLOCK_RESOURCES, block_hosts=PAGE_BLOCK_HOSTS)
    try:
        res = driver.nav(SITE + "/", referer="https://www.google.com/", mode="csr")
        status = res.get("status")
        if status not in (None, 200):
            raise RuntimeError(f"homepage answered HTTP {status} ({res.get('challenge_title') or 'no title'})")
        # Let Akamai's sensor validate the page (_abck carries "~0~"), then
        # prove the page with one tiny gateway call: Akamai judges the
        # egress IP too, and a page on a flagged IP is refused even with a
        # validated _abck (the GKE pod's own IP, 2026-10-14).
        for step in range(SENSOR_ROUNDS):
            driver.call(lambda page, s=step: _wiggle(page, s))
            time.sleep(SENSOR_INTERVAL)
            abck = next((c["value"] for c in driver.cookies()
                         if c.get("name") == "_abck" and "homedepot.com" in (c.get("domain") or "")), "")
            if "~0~" in abck:
                break
        # Akamai starts accepting a page a few seconds AFTER _abck validates
        # (the Windows VPS: refused at validation, 200 from ~6 s later), so
        # the probe gets a few tries with pointer activity in between.
        probe = 0
        for attempt in range(PROBE_ATTEMPTS):
            probe, _ = _fetch_on(driver, "storeSearch", {"operationName": "storeSearch", "query": PROBE_QUERY,
                                                         "variables": {"storeSearchInput": "30339", "pagesize": "1"}})
            if probe == 200:
                break
            driver.call(lambda page, s=attempt: _wiggle(page, SENSOR_ROUNDS + s))
            time.sleep(PROBE_INTERVAL)
        if probe != 200:
            raise RuntimeError(f"probe call refused (HTTP {probe}) — Akamai rejects this egress")
    except Exception:
        driver.close()
        raise
    print(f"homedepot: page ready ({label})")
    return driver


def _open_page():
    global _direct_skip_until
    last = None
    configured = config.homedepot_proxy()
    for proxy in _proxy_candidates():
        try:
            return _open_page_once(proxy)
        except Exception as e:
            last = e
            print(f"homedepot: page open failed ({type(e).__name__}: {e})")
            if proxy == configured and configured is None:
                # The direct egress is flagged: go straight to the exits
                # for a while instead of re-proving it on every open.
                _direct_skip_until = time.monotonic() + config.HOMEDEPOT_DIRECT_SKIP
    raise HomeDepotBlocked(f"could not open a homedepot.com page: {last}")


def _close(slot):
    driver, slot["driver"] = slot["driver"], None
    if driver is not None:
        try:
            driver.close()
        except Exception:
            pass


def _release(slot):
    _free.put(slot)


def _acquire():
    """A free slot with an open, fresh page (opening one if needed)."""
    global _slot_count
    try:
        slot = _free.get_nowait()
    except queue.Empty:
        slot = None
        with _slots_lock:
            if _slot_count < max(int(config.HOMEDEPOT_BROWSER_PAGES), 1):
                _slot_count += 1
                slot = {"driver": None, "opened_at": 0.0}
        if slot is None:
            try:
                slot = _free.get(timeout=ACQUIRE_TIMEOUT)
            except queue.Empty:
                raise HomeDepotBusy("every homedepot.com page is busy, retry later")
    if slot["driver"] is not None and time.monotonic() - slot["opened_at"] > config.HOMEDEPOT_BROWSER_MAX_AGE:
        _close(slot)
    if slot["driver"] is None:
        try:
            slot["driver"] = _open_page()
            slot["opened_at"] = time.monotonic()
        except Exception:
            _release(slot)
            raise
    return slot


def warm():
    """Open one page ahead of the first request (optional, e.g. a smoke test)."""
    _release(_acquire())


# ---- one call ----------------------------------------------------------------------

def _fetch(slot, operation, payload):
    """One gateway POST as an in-page fetch -> (status, body text)."""
    return _fetch_on(slot["driver"], operation, payload)


def _fetch_on(driver, operation, payload):
    from patchright_driver import _FETCH_JS
    experience, current = EXPERIENCES.get(operation, ("general-merchandise", "/"))
    args = {
        "url": f"{GATEWAY}?opname={operation}",
        "method": "POST",
        "headers": {"content-type": "application/json", "accept": "*/*", "x-experience-name": experience,
                    "x-current-url": current, "x-hd-dc": "origin", "x-api-cookies": "{}", "x-debug": "false"},
        "body": json.dumps(payload),
        "referrer": SITE + "/",
        "timeoutMs": TIMEOUT * 1000,
    }
    res = driver.call(lambda page: page.evaluate(_FETCH_JS, args), timeout=TIMEOUT + 15) or {}
    if not res.get("ok"):
        raise RuntimeError(res.get("error") or "fetch failed")
    return int(res.get("status") or 0), res.get("body") or ""


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
    """POST one operation through a homedepot.com page; return the `data`
    member (or `data[root]`).

    A refused or failed page is replaced and the call retried on the next
    one. GraphQL errors with no usable data raise HomeDepotUpstreamError (a
    validation error names the field, so a schema change is visible in the
    message)."""
    payload = {"operationName": operation, "variables": variables, "query": query}
    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        slot = _acquire()
        try:
            status, text = _fetch(slot, operation, payload)
        except Exception as e:
            # A failed or wedged fetch: the page is suspect, replace it.
            _close(slot)
            _release(slot)
            last = HomeDepotUpstreamError(f"{operation}: in-page fetch failed: {type(e).__name__}: {e}")
            time.sleep(config.RETRY_BACKOFF * attempt)
            continue
        if _is_refusal(status, text):
            dump_debug(f"refused_{operation}", text)
            print(f"homedepot: {operation} refused (HTTP {status}), replacing the page "
                  f"(attempt {attempt}/{MAX_ATTEMPTS})")
            _close(slot)
            _release(slot)
            last = HomeDepotBlocked(f"Akamai refused the request (HTTP {status})")
            continue
        _release(slot)
        if status == 403:
            # A 403 is a rule on the request itself (seen for searchModel
            # pageSize > 24), never the page's verdict (that is the 206).
            dump_debug(f"forbidden_{operation}", text)
            raise HomeDepotBadRequest(f"the gateway refused this {operation} request (HTTP 403)")
        if status >= 500:
            last = HomeDepotUpstreamError(f"{operation}: HTTP {status}")
            time.sleep(config.RETRY_BACKOFF * attempt)
            continue
        if status != 200:
            raise HomeDepotUpstreamError(f"{operation}: HTTP {status}: {text[:200]}")
        try:
            body = json.loads(text)
        except Exception:
            dump_debug(f"nonjson_{operation}", text)
            raise HomeDepotUpstreamError(f"{operation}: non-JSON reply")
        return _value_of(operation, body, root)
    raise last or HomeDepotUpstreamError(f"{operation}: no attempt succeeded")


if __name__ == "__main__":
    # Smoke test: open one page, then run a store lookup, a search and a
    # product read through it.
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
