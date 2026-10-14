"""Configuration for the Home Depot Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT                       port the API listens on (default 8000)
    HOMEDEPOT_BROWSER_PAGES    Chrome pages serving requests at once (default 2)
    HOMEDEPOT_PROXY            proxy URL for every Chrome page, e.g.
                               http://user:pass@host:port (default: none —
                               direct). Home Depot judges the IP a page runs
                               on, so use a STICKY proxy, never a rotating one.
    HOMEDEPOT_FALLBACK_PROXY   sticky proxy a page retries through when your
                               own IP is refused (default: none)
    HOMEDEPOT_STORE_ID         store prices / stock default to (default 121,
                               Cumberland, Atlanta GA)
    HOMEDEPOT_ZIP              ZIP of that store (default 30339)

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# Every request runs as an in-page fetch inside a headed Chrome page parked
# on homedepot.com. Up to HOMEDEPOT_BROWSER_PAGES pages (one Chrome each)
# open on demand, each serving one request at a time; a page is replaced
# when Home Depot refuses it or past HOMEDEPOT_BROWSER_MAX_AGE.
HOMEDEPOT_BROWSER_PAGES = int(os.environ.get("HOMEDEPOT_BROWSER_PAGES", "2"))
HOMEDEPOT_BROWSER_MAX_AGE = 30 * 60      # seconds
# When your own IP is refused and HOMEDEPOT_FALLBACK_PROXY is set, new pages
# skip the direct connection for this long.
HOMEDEPOT_DIRECT_SKIP = 60 * 60          # seconds

HOMEDEPOT_DEFAULT_STORE_ID = os.environ.get("HOMEDEPOT_STORE_ID", "121")
HOMEDEPOT_DEFAULT_ZIP = os.environ.get("HOMEDEPOT_ZIP", "30339")


def homedepot_proxy():
    return os.environ.get("HOMEDEPOT_PROXY") or None


def homedepot_fallback_proxy():
    return os.environ.get("HOMEDEPOT_FALLBACK_PROXY") or None


def resolve_timezone(proxy, timezone=None, geoip_timezone=None, label="driver"):
    """The JS timezone the mint browser gets on `proxy`: the exit IP's own
    zone (looked up through the proxy), else `timezone` (None = system TZ)."""
    if isinstance(geoip_timezone, str) and geoip_timezone:
        return geoip_timezone
    if not (geoip_timezone and proxy):
        return timezone
    try:
        from curl_cffi import requests
        geo = requests.get("http://ip-api.com/json/?fields=status,timezone",
                           proxies={"http": proxy, "https": proxy}, timeout=12).json()
        if geo.get("status") == "success" and geo.get("timezone"):
            return geo["timezone"]
    except Exception:
        pass
    print(f"{label}: exit geo lookup failed; keeping timezone={timezone}")
    return timezone
