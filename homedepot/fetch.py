"""Home Depot transport: plain curl_cffi against homedepot.com's own
federation GraphQL gateway, with an Akamai identity minted by one headed
patchright page-load. No chrome pool (homedepot is in config.POOLLESS_FLAGS).

Every page of homedepot.com is built from ONE endpoint:

    POST https://apionline.homedepot.com/federation-gateway/graphql?opname=<op>

(search / browse = searchModel, product page = productClientOnlyProduct,
reviews, questionsAnswers, storeSearch, aislebay, savingsDepartment,
specialBuyMetadata — the documents live in homedepot/queries.py). The
gateway is fronted by Akamai Bot Manager, validated live 2026-10-14:

  * Plain curl_cffi (chrome impersonation) with no cookies, with the
    homepage's own cookies, or through a US residential exit answers HTTP
    206 {"data":{"Generic Errors API":null},"error":[...]} on every
    operation; every www page except the homepage is a 403 "Error Page".
  * The four Akamai cookies of a browser whose sensor validated — _abck
    (carrying "~0~"), bm_sz, bm_s, bm_so — make curl_cffi pass: 40/40
    sequential, 40/40 over 8 threads, still valid 15 min after the mint.
    PerimeterX (also on the site) is NOT consulted by the gateway.
  * The cookies are bound to the egress IP that minted them: the same set
    replayed through another exit is 206 again. The mint browser and the
    requests therefore share one proxy (or both go direct).
  * The gateway Set-Cookies a NEW _abck / bm_sz / bm_s on every reply, and
    letting those replace the minted ones kills the identity on the very
    next request (1/60 passed). The minted cookies are replayed PINNED:
    the per-thread session's jar is cleared before each call.
  * A headless Chrome never gets its _abck validated (the sensor needs a
    headed window + a little pointer movement: ~2 s with mouse moves and a
    scroll on the homepage). The mint blocks images / fonts / media.

  * From a datacenter IP (the GKE pod, validated 2026-10-14) the replay
    never passes: the sensor rarely validates there, and even cookies that
    did validate — direct or through sticky residential exits — are 206 over
    curl_cffi (every chrome124…chrome150 target), while the SAME browser's
    own in-page fetch of the same call answers 200.

So: one process-wide identity {cookies, user agent, proxy, minted_at},
minted lazily on the first request (single-flight — threads that waited on
the mint lock reuse the winner's identity), re-minted when it is older
than config.HOMEDEPOT_IDENTITY_MAX_AGE or when the gateway refuses it
(206 / 401 / 403 — the request is retried once on the new identity). A
mint tries the direct egress first and falls back to sticky residential
exits (config.homedepot_fallback_proxy) when the homepage itself is
refused or the sensor never validates.

BROWSER MODE (the headful patchright fallback): when curl is refused even
on a freshly minted identity (or no identity can be minted), the process
switches to in-page fetches — every gateway POST runs as fetch() inside ONE
long-lived headed patchright page parked on homedepot.com — for
config.HOMEDEPOT_BROWSER_MODE_TTL seconds, then tries curl again. The page
is recycled when it is refused, wedged, or older than
config.HOMEDEPOT_BROWSER_MAX_AGE. Page ops are serialized on the driver's
owner thread, so browser mode trades throughput (~1-2 calls/s) for passing.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  HomeDepotUpstreamError  transport failure / 5xx / GraphQL errors — retryable
  HomeDepotBlocked        Akamai refused the identity (206 / 401 / 403) — retryable on a new mint
  HomeDepotBadRequest     the gateway rejected the arguments            — never retried
  HomeDepotNotFound       entity does not exist                         — never retried

Run this file directly for a smoke test:
    python homedepot/fetch.py
"""
import json
import os
import sys
import threading
import time
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

SITE = "https://www.homedepot.com"
GATEWAY = "https://apionline.homedepot.com/federation-gateway/graphql"
IMPERSONATE = "chrome"
TIMEOUT = 45
MAX_ATTEMPTS = 3            # identities tried per request
AKAMAI_COOKIES = ("_abck", "bm_sz", "bm_s", "bm_so")
MINT_BLOCK_RESOURCES = ("image", "font", "media")
MINT_BLOCK_HOSTS = (
    "collector-pxj770cp7y.px-cloud.net", "c.go-mpulse.net", "*.akstat.io",
    "www.google-analytics.com", "*.doubleclick.net", "*.googletagmanager.com",
    "*.adobedc.net", "*.demdex.net", "*.quantummetric.com", "*.forter.com",
    "*.bazaarvoice.com", "*.qualtrics.com", "*.paypal.com", "*.segment.io",
    "*.cquotient.com", "*.liveperson.net", "*.lpsnmedia.net",
)
MINT_SENSOR_TIMEOUT = 25    # seconds of pointer activity before giving up on _abck
MINT_POLL_INTERVAL = 1.5

# x-experience-name the site sends per page type; the gateway does not
# enforce it, but the pairs below are the ones observed.
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
    """Transport failure, 5xx or a GraphQL error — retryable."""


class HomeDepotBlocked(HomeDepotUpstreamError, Blocked):
    """Akamai refused the identity (206 / 401 / 403) — retryable on a new mint."""


class HomeDepotBadRequest(BadRequest):
    """The gateway rejected the arguments — never retried."""


class HomeDepotNotFound(NotFound):
    """Entity does not exist — never retried."""


# ---- identity ------------------------------------------------------------------
_state_lock = threading.Lock()
_mint_lock = threading.Lock()
_identity = None
_local = threading.local()
_browser_lock = threading.Lock()
_browser = None              # {"driver", "created_at"} — browser mode's page
_browser_mode_until = 0.0    # monotonic deadline of browser mode (0 = curl)


def _proxy_candidates():
    """Proxies a mint tries in order: the configured sticky exit (or direct),
    then fresh fallback exits."""
    first = config.homedepot_proxy()
    out = [first]
    for _ in range(max(config.HOMEDEPOT_MINT_ATTEMPTS - 1, 0)):
        fallback = config.homedepot_fallback_proxy()
        if fallback:
            out.append(fallback)
    return out


def _wiggle(page, step):
    """A little pointer + scroll activity for Akamai's sensor."""
    page.mouse.move(180 + step * 23, 260 + step * 7)
    page.mouse.move(420 + step * 5, 340 + step * 11, steps=10)
    page.mouse.wheel(0, 260)


def _mint_once(proxy):
    """One headed patchright homepage load through `proxy` (None = direct);
    returns the identity once the sensor validated _abck. Raises
    RuntimeError when the homepage is refused or _abck never validates."""
    from chrome_manager import create_scope
    from patchright_driver import PatchrightDriver

    label = f"exit port {urlsplit(proxy).port}" if proxy else "direct egress"
    print(f"homedepot: minting Akamai identity via headed patchright ({label})...")
    with create_scope():
        driver = PatchrightDriver(proxy_url=proxy, headless=False,
                                  geoip_timezone=bool(proxy),
                                  block_resources=MINT_BLOCK_RESOURCES,
                                  block_hosts=MINT_BLOCK_HOSTS)
    try:
        res = driver.nav(SITE + "/", referer="https://www.google.com/", mode="csr")
        status = res.get("status")
        if status not in (None, 200):
            raise RuntimeError(f"homepage answered HTTP {status} ({res.get('challenge_title') or 'no title'})")
        user_agent = driver.evaluate("() => navigator.userAgent")
        deadline = time.monotonic() + MINT_SENSOR_TIMEOUT
        step = 0
        while True:
            driver.call(lambda page, s=step: _wiggle(page, s))
            time.sleep(MINT_POLL_INTERVAL)
            cookies = {c["name"]: c["value"] for c in driver.cookies()
                       if "homedepot.com" in (c.get("domain") or "")}
            if "~0~" in cookies.get("_abck", "") and all(n in cookies for n in AKAMAI_COOKIES):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Akamai sensor never validated _abck")
            step += 1
    finally:
        driver.close()
    pinned = {name: cookies[name] for name in AKAMAI_COOKIES}
    print(f"homedepot: identity minted ({label}, {step + 1} sensor rounds)")
    return {"cookies": pinned, "user_agent": user_agent, "proxy": proxy,
            "minted_at": time.monotonic()}


def _mint():
    last = None
    for proxy in _proxy_candidates():
        try:
            return _mint_once(proxy)
        except Exception as e:
            last = e
            print(f"homedepot: identity mint failed ({type(e).__name__}: {e})")
    raise HomeDepotBlocked(f"could not mint an Akamai identity: {last}")


def _current_identity():
    with _state_lock:
        identity = _identity
    if identity and time.monotonic() - identity["minted_at"] <= config.HOMEDEPOT_IDENTITY_MAX_AGE:
        return identity
    return None


def _get_identity():
    """The live identity, minting one when there is none or it aged out
    (single-flight)."""
    global _identity
    identity = _current_identity()
    if identity:
        return identity
    with _mint_lock:
        identity = _current_identity()
        if identity is None:
            identity = _mint()
            with _state_lock:
                _identity = identity
        return identity


def _invalidate(stale):
    """Drop the identity iff it is still the one that was refused."""
    global _identity
    with _state_lock:
        if _identity is stale:
            _identity = None


def warm_identity():
    """Mint ahead of the first request (optional, e.g. from a smoke test)."""
    return _get_identity()


# ---- sessions --------------------------------------------------------------------

def _session(proxy):
    """One curl session per worker thread and proxy (keep-alive); its jar is
    cleared before every call so the gateway's Set-Cookie never replaces
    the minted cookies."""
    sess = getattr(_local, "session", None)
    if sess is None or getattr(_local, "proxy", None) != proxy:
        _drop_session()
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        _local.session = sess
        _local.proxy = proxy
    sess.cookies.clear()
    return sess


def _drop_session():
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def dump_debug(name, text):
    dbg = os.environ.get("HOMEDEPOT_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


# ---- requests ---------------------------------------------------------------------

def _headers(operation, identity):
    experience, current = EXPERIENCES.get(operation, ("general-merchandise", "/"))
    return {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": SITE,
        "referer": SITE + "/",
        "user-agent": identity["user_agent"],
        "x-experience-name": experience,
        "x-current-url": current,
        "x-hd-dc": "origin",
        "x-api-cookies": "{}",
        "x-debug": "false",
    }


def _is_refusal(resp):
    """Akamai's verdicts: 206 with the "Generic Errors API" body, or a 401
    (HTML) in place of the JSON reply. A 403 is a request rule (see graphql)."""
    if resp.status_code in (206, 401):
        return True
    body = resp.text or ""
    return resp.status_code != 200 and "Generic Errors" in body


def _graphql_errors(body):
    errors = body.get("errors") if isinstance(body, dict) else None
    if isinstance(errors, list) and errors:
        return [e.get("message") for e in errors if isinstance(e, dict)]
    return []


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


def _check_status(operation, status, text):
    """Map a non-refusal HTTP status; returns normally for a 200."""
    if status == 403:
        # A 403 is a rule on the request itself (seen for searchModel
        # pageSize > 24), never the identity verdict (that is the 206):
        # fail fast instead of burning a mint per call.
        dump_debug(f"forbidden_{operation}", text)
        raise HomeDepotBadRequest(f"the gateway refused this {operation} request (HTTP 403)")
    if status >= 500:
        raise HomeDepotUpstreamError(f"{operation}: HTTP {status}")
    if status != 200:
        raise HomeDepotUpstreamError(f"{operation}: HTTP {status}: {(text or '')[:200]}")


def _parse_json(operation, text):
    try:
        import json
        return json.loads(text)
    except Exception:
        dump_debug(f"nonjson_{operation}", text)
        raise HomeDepotUpstreamError(f"{operation}: non-JSON reply")


# ---- browser mode ---------------------------------------------------------------

def _browser_mode_active():
    return time.monotonic() < _browser_mode_until


def _enter_browser_mode(reason):
    global _browser_mode_until
    with _state_lock:
        already = time.monotonic() < _browser_mode_until
        _browser_mode_until = time.monotonic() + config.HOMEDEPOT_BROWSER_MODE_TTL
    if not already:
        print(f"homedepot: {reason} — switching to in-browser fetches for "
              f"{config.HOMEDEPOT_BROWSER_MODE_TTL // 60} min")


def _close_browser(stale=None):
    """Close the browser-mode page iff it is still `stale` (or any, if None)."""
    global _browser
    with _browser_lock:
        current = _browser
        if current is None or (stale is not None and current is not stale):
            return
        _browser = None
    try:
        current["driver"].close()
    except Exception:
        pass


def _open_browser():
    """One headed patchright page parked on the homepage (a little pointer
    activity lets the sensor post); the proxy is the configured one (direct
    by default)."""
    from chrome_manager import create_scope
    from patchright_driver import PatchrightDriver

    proxy = config.homedepot_proxy()
    print("homedepot: opening the browser-mode page via headed patchright "
          f"({'exit port ' + str(urlsplit(proxy).port) if proxy else 'direct egress'})...")
    with create_scope():
        driver = PatchrightDriver(proxy_url=proxy, headless=False, geoip_timezone=bool(proxy),
                                  block_resources=MINT_BLOCK_RESOURCES, block_hosts=MINT_BLOCK_HOSTS)
    try:
        res = driver.nav(SITE + "/", referer="https://www.google.com/", mode="csr")
        if res.get("status") not in (None, 200):
            raise RuntimeError(f"homepage answered HTTP {res.get('status')}")
        for step in range(3):
            driver.call(lambda page, s=step: _wiggle(page, s))
            time.sleep(1)
    except Exception:
        driver.close()
        raise
    return {"driver": driver, "created_at": time.monotonic()}


def _get_browser():
    global _browser
    with _browser_lock:
        current = _browser
        if current and time.monotonic() - current["created_at"] <= config.HOMEDEPOT_BROWSER_MAX_AGE:
            return current
        _browser = None
    if current:
        try:
            current["driver"].close()
        except Exception:
            pass
    with _mint_lock:      # one launch at a time (shares the mint's lock)
        with _browser_lock:
            if _browser is not None:
                return _browser
        opened = _open_browser()
        with _browser_lock:
            _browser = opened
        return opened


def _browser_post(operation, payload):
    """One gateway POST as an in-page fetch -> (status, text)."""
    from patchright_driver import _FETCH_JS
    import json
    browser = _get_browser()
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
    try:
        res = browser["driver"].call(lambda page: page.evaluate(_FETCH_JS, args), timeout=TIMEOUT + 15) or {}
    except Exception as e:
        _close_browser(browser)
        raise HomeDepotUpstreamError(f"{operation}: in-browser fetch failed: {type(e).__name__}: {e}")
    if not res.get("ok"):
        _close_browser(browser)
        raise HomeDepotUpstreamError(f"{operation}: in-browser fetch failed: {res.get('error')}")
    return int(res.get("status") or 0), res.get("body") or "", browser


def _graphql_browser(operation, payload, root):
    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            status, text, browser = _browser_post(operation, payload)
        except HomeDepotUpstreamError as e:
            last = e
            time.sleep(config.RETRY_BACKOFF * attempt)
            continue
        if status in (206, 401) or (status != 200 and "Generic Errors" in text):
            dump_debug(f"browser_refused_{operation}", text)
            print(f"homedepot: in-browser {operation} refused (HTTP {status}), recycling the page "
                  f"(attempt {attempt}/{MAX_ATTEMPTS})")
            _close_browser(browser)
            last = HomeDepotBlocked(f"Akamai refused the in-browser request (HTTP {status})")
            continue
        if status >= 500:
            last = HomeDepotUpstreamError(f"{operation}: HTTP {status}")
            time.sleep(config.RETRY_BACKOFF * attempt)
            continue
        _check_status(operation, status, text)
        return _value_of(operation, _parse_json(operation, text), root)
    raise last or HomeDepotUpstreamError(f"{operation}: no attempt succeeded")


# ---- the transport ---------------------------------------------------------------

def graphql(operation, query, variables, *, root=None):
    """POST one operation; return the `data` member (or `data[root]`).

    curl_cffi with the minted identity first; a refusal re-mints, and a
    refusal on a fresh identity (or a failed mint) switches the process to
    browser mode (in-page fetches) for a while. GraphQL errors with no
    usable data raise HomeDepotUpstreamError (a validation error names the
    field, so a schema change is visible in the message)."""
    payload = {"operationName": operation, "variables": variables, "query": query}
    if _browser_mode_active():
        return _graphql_browser(operation, payload, root)
    last = None
    refusals = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            identity = _get_identity()
        except HomeDepotBlocked as e:
            _enter_browser_mode(f"no identity could be minted ({e})")
            return _graphql_browser(operation, payload, root)
        try:
            resp = _session(identity["proxy"]).post(
                GATEWAY, params={"opname": operation},
                headers=_headers(operation, identity), cookies=identity["cookies"],
                json=payload, timeout=TIMEOUT)
        except Exception as e:
            last = HomeDepotUpstreamError(f"{operation} request failed: {type(e).__name__}: {e}")
            _drop_session()
            time.sleep(config.RETRY_BACKOFF * attempt)
            continue
        if resp.status_code != 403 and _is_refusal(resp):
            dump_debug(f"refused_{operation}", resp.text)
            refusals += 1
            _invalidate(identity)
            if refusals >= 2:
                _enter_browser_mode(f"{operation} refused over curl on a fresh identity")
                return _graphql_browser(operation, payload, root)
            print(f"homedepot: {operation} refused (HTTP {resp.status_code}), re-minting identity "
                  f"(attempt {attempt}/{MAX_ATTEMPTS})")
            last = HomeDepotBlocked(f"Akamai refused the request (HTTP {resp.status_code})")
            continue
        if resp.status_code >= 500:
            last = HomeDepotUpstreamError(f"{operation}: HTTP {resp.status_code}")
            time.sleep(config.RETRY_BACKOFF * attempt)
            continue
        _check_status(operation, resp.status_code, resp.text)
        return _value_of(operation, _parse_json(operation, resp.text), root)
    raise last or HomeDepotUpstreamError(f"{operation}: no attempt succeeded")


def _looks_like_not_found(message):
    """"ItemId: 999999999 not found", "Record Not Found" (a parent id that
    is not a product)."""
    return "not found" in (message or "").lower()


def _looks_like_bad_input(message):
    low = (message or "").lower()
    return any(token in low for token in ("invalid", "must be", "not a valid", "bad request"))


if __name__ == "__main__":
    # Smoke test: mint one identity, run a search, a store lookup and a
    # product read; the second call reuses the identity (no browser).
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
