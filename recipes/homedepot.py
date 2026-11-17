"""Home Depot federation gateway (homedepot/fetch.py): Akamai Bot Manager
judges both the browser and the egress IP, and the GraphQL gateway only
answers an in-page fetch from a page whose `_abck` sensor cookie it has
validated. Phase 5 re-split (the old Windows box ran the whole module):
the box keeps parked pages, one per key GKE sends (the egress, or a session
id for a second page of the same egress) - warm = load the homepage, give
the sensor pointer/scroll activity until `_abck` carries "~0~", then prove
the page with a tiny storeSearch probe (Akamai accepts a page a few seconds
after validation) - and every gateway POST is an in-page fetch on it.
Parsing, pagination, cache and the choice of egress (the box's own IP while
Akamai accepts it, residential exits only while it is skipped) stay on GKE,
which sends the proxy per call. A 206/401 refusal fails the lease so the
next call relaunches.

The warm-up is 10-15 s and a call on a parked page 0.3-1 s, so a page stays
parked for as long as it may live (idle_seconds = max_age, 2026-11-12; it
was 300 s, and a customer calling every few minutes paid the warm-up on
every call). A parked page sits on /robots.txt: no timers, no traffic."""
import time

from browser_worker.types import PageFetch, RecipeError

SITE = "https://www.homedepot.com"
GATEWAY = "https://apionline.homedepot.com/federation-gateway/graphql"
PARK_PATH = "/robots.txt"
SENSOR_ROUNDS = 8
SENSOR_INTERVAL = 1.5
PROBE_ATTEMPTS = 5
PROBE_INTERVAL = 2.5
PROBE_QUERY = ("query storeSearch($storeSearchInput: String, $pagesize: String) "
               "{ storeSearch(storeSearchInput: $storeSearchInput, pagesize: $pagesize) { stores { storeId } } }")
PROBE_BODY = ('{"operationName":"storeSearch","query":"%s","variables":{"storeSearchInput":"30339","pagesize":"1"}}'
              % PROBE_QUERY.replace('"', '\\"'))
PROBE_HEADERS = {"content-type": "application/json", "accept": "*/*", "x-experience-name": "store-locator",
                 "x-current-url": "/l/store-locator", "x-hd-dc": "origin", "x-api-cookies": "{}", "x-debug": "false"}
PAGE_BLOCK_RESOURCES = ("image", "font", "media")
PAGE_BLOCK_HOSTS = ("collector-pxj770cp7y.px-cloud.net", "c.go-mpulse.net", "*.akstat.io",
                    "www.google-analytics.com", "*.doubleclick.net", "*.googletagmanager.com")


def _wiggle(page, step):
    """A little pointer + scroll activity for Akamai's sensor."""
    page.mouse.move(180 + step * 23, 260 + step * 7)
    page.mouse.move(420 + step * 5, 340 + step * 11, steps=10)
    page.mouse.wheel(0, 260)


def is_refusal(status, text):
    """Akamai's verdicts: 206 with the "Generic Errors API" body, or a 401."""
    return status in (206, 401) or (status != 200 and "Generic Errors" in (text or ""))


class HomeDepot(PageFetch):
    name = "homedepot"
    headless = False
    variants = {"": SITE + "/"}
    mode = "in_page"
    block_resources = PAGE_BLOCK_RESOURCES
    block_hosts = PAGE_BLOCK_HOSTS
    park_url = SITE + PARK_PATH
    max_age = 30 * 60                 # HOMEDEPOT_BROWSER_MAX_AGE: a page is replaced after this long
    idle_seconds = max_age            # parked until then: the next call must not pay the warm-up
    max_browsers = 2                  # HOMEDEPOT_BROWSER_PAGES

    def warm(self, driver, variant):
        res = driver.nav(SITE + "/", referer="https://www.google.com/", mode="csr") or {}
        status = res.get("status")
        if status not in (None, 200):
            raise RecipeError(f"homedepot: homepage answered HTTP {status} ({res.get('challenge_title') or 'no title'}); "
                              "Akamai refuses this egress")
        for step in range(SENSOR_ROUNDS):
            driver.call(lambda page, s=step: _wiggle(page, s))
            time.sleep(SENSOR_INTERVAL)
            abck = next((c["value"] for c in driver.cookies()
                         if c.get("name") == "_abck" and "homedepot.com" in (c.get("domain") or "")), "")
            if "~0~" in abck:
                break
        probe = 0
        for attempt in range(PROBE_ATTEMPTS):
            r = driver.request("POST", f"{GATEWAY}?opname=storeSearch", headers=PROBE_HEADERS, body=PROBE_BODY,
                               referrer=SITE + "/")
            probe = r.status_code
            if probe == 200:
                break
            driver.call(lambda page, s=attempt: _wiggle(page, SENSOR_ROUNDS + s))
            time.sleep(PROBE_INTERVAL)
        if probe != 200:
            raise RecipeError(f"homedepot: probe call refused (HTTP {probe}); Akamai rejects this egress")

    def fetch_one(self, driver, url, method, headers, body):
        r = driver.request(method or "POST", url, headers=headers or None, body=body, referrer=SITE + "/")
        if not r.status_code and r.error:
            raise RecipeError(f"homedepot: in-page fetch failed: {r.error}")
        out = {"status": r.status_code, "headers": dict(r.headers or {}), "body": r.text, "final_url": r.url or url}
        if is_refusal(out["status"], out["body"]):
            raise RecipeError(f"homedepot: Akamai refused the request (HTTP {out['status']}); page dropped")
        return out


RECIPE = HomeDepot
