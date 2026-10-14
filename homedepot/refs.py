"""Home Depot reference parsing: ONE param per input that auto-detects its
forms (tripadvisor QueryOrIdField convention — never a sibling `url`/`id`
pair).

  product    320326787 (the internet number / item id, 9 digits)
             | https://www.homedepot.com/p/Milwaukee-M18-.../320326787
             | https://www.homedepot.com/pep/.../320326787
  products   comma-separated item ids and/or product links (max 25)
  category   N-5yc1vZc27f (the browse code, also carries brand / refinement
             codes such as N-5yc1vZzv or N-5yc1vZc27fZzv)
             | https://www.homedepot.com/b/Tools-Power-Tools-Drills/N-5yc1vZc27f
             | https://www.homedepot.com/b/Milwaukee/N-5yc1vZzv (a brand page)
  store      121 / 0121 (the store number)
             | https://www.homedepot.com/l/Cumberland/GA/Atlanta/30339/121
             | 30339 (a 5-digit ZIP: the nearest store — resolved by shared.locate_store)
  location   30339 (ZIP) | "Austin, TX" (city, state) | 33.86,-84.47 (lat,lng)
             | 121 (store number) | a store link

Links to other sites raise ValueError with a usable message.
"""
import re
from urllib.parse import quote, urlparse

SITE = "https://www.homedepot.com"
IMAGE_HOST = "https://images.thdstatic.com"

_ITEM_ID_RE = re.compile(r"^\d{6,12}$")
_NAV_RE = re.compile(r"^N-[A-Za-z0-9]+$")
_STORE_RE = re.compile(r"^\d{1,4}$")
_ZIP_RE = re.compile(r"^\d{5}$")
_LATLNG_RE = re.compile(r"^(-?\d{1,3}(?:\.\d+)?)\s*[,; ]\s*(-?\d{1,3}(?:\.\d+)?)$")
MAX_BULK = 25


def _is_url(value):
    low = value.lower()
    return low.startswith(("http://", "https://", "//", "homedepot.com/", "www.homedepot.com/"))


def _segments(value):
    """A homedepot.com link -> path segments. Raises ValueError for another site."""
    url = value
    if url.startswith("//"):
        url = "https:" + url
    elif not url.lower().startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not (host == "homedepot.com" or host.endswith(".homedepot.com")):
        raise ValueError("not a homedepot.com link")
    return [s for s in parsed.path.split("/") if s]


# ---- links ----------------------------------------------------------------------

def absolute_link(path):
    """A site-relative path ('/p/x/320326787', '/b/Tools/N-5yc1vZc1xy') ->
    absolute; absolute links pass through; empty -> None."""
    if not isinstance(path, str) or not path.strip():
        return None
    path = path.strip()
    if path.startswith("//"):
        return "https:" + path
    if path.startswith("http"):
        return path
    return SITE + (path if path.startswith("/") else "/" + path)


def product_link(item_id, canonical=None):
    if canonical:
        return absolute_link(canonical)
    return f"{SITE}/p/{item_id}" if item_id else None


def search_link(query):
    return f"{SITE}/s/{quote(query)}" if query else None


def store_link(path):
    return absolute_link(path)


def image_link(template, size="1000"):
    """'.../x-64_<SIZE>.jpg' -> the 1000-px rendition (sizes: 65 100 145 300
    400 600 1000)."""
    if not isinstance(template, str) or not template.strip():
        return None
    return absolute_link(template.replace("<SIZE>", str(size)))


def category_code(path):
    """The browse code inside any path or link ('/b/Tools/N-5yc1vZc1xy',
    'https://www.homedepot.com/b/Milwaukee/N-5yc1vZzv?x') -> 'N-5yc1vZc1xy'."""
    if not isinstance(path, str):
        return None
    match = re.search(r"/(N-[A-Za-z0-9]+)", path)
    return match.group(1) if match else None


# ---- normalisation -----------------------------------------------------------------

def pad_store_id(value):
    """'121' -> '0121' (the gateway's inventory operations want the 4-digit
    form; the pages and search accept either)."""
    digits = str(value or "").strip()
    if not digits:
        return None
    return digits.zfill(4) if digits.isdigit() else digits


def plain_store_id(value):
    """'0121' -> '121' (the id the store page link and the API use)."""
    digits = str(value or "").strip()
    if not digits:
        return None
    return str(int(digits)) if digits.isdigit() else digits


# ---- resolvers ----------------------------------------------------------------------

def resolve_product(value):
    """Item id (internet number) or a homedepot.com product link -> the item id."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("product is required")
    if _is_url(value):
        try:
            segments = _segments(value)
        except ValueError:
            raise ValueError("product must be a homedepot.com product link or an item id")
        lowered = [s.lower() for s in segments]
        candidate = None
        if lowered and lowered[0] in ("p", "pep") and len(segments) >= 2:
            candidate = segments[-1].split("?")[0]
        if not candidate or not _ITEM_ID_RE.match(candidate):
            raise ValueError("product link must look like "
                             "https://www.homedepot.com/p/<product-name>/320326787")
        value = candidate
    if not _ITEM_ID_RE.match(value):
        raise ValueError("product must be a Home Depot item id / internet number (320326787) "
                         "or a homedepot.com product link")
    return value


def resolve_products(value):
    """Comma-separated item ids / links -> [item id, ...] (deduped, order
    kept, at most MAX_BULK)."""
    out = []
    for raw in str(value or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        item = resolve_product(raw)
        if item not in out:
            out.append(item)
    if not out:
        raise ValueError("products is required")
    if len(out) > MAX_BULK:
        raise ValueError(f"at most {MAX_BULK} products per call")
    return out


def resolve_category(value):
    """Browse code (N-5yc1vZc27f) or a homedepot.com /b/ link -> the code."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("category is required")
    if _is_url(value):
        try:
            segments = _segments(value)
        except ValueError:
            raise ValueError("category must be a homedepot.com browse link (/b/...) or a browse code (N-5yc1vZc27f)")
        codes = [s.split("?")[0] for s in segments if _NAV_RE.match(s.split("?")[0])]
        if not codes:
            raise ValueError("category link must carry a browse code, like "
                             "https://www.homedepot.com/b/Tools-Power-Tools-Drills/N-5yc1vZc27f")
        return codes[0]
    if not _NAV_RE.match(value):
        raise ValueError("category must be a Home Depot browse code (N-5yc1vZc27f) or a homedepot.com browse link")
    return value


def resolve_store(value):
    """Store number, a store link, or a ZIP -> {"id": "121"} | {"zip": "30339"}."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("store is required")
    if _is_url(value):
        try:
            segments = _segments(value)
        except ValueError:
            raise ValueError("store must be a homedepot.com store link, a store number or a ZIP code")
        if len(segments) >= 2 and segments[0].lower() == "l" and _STORE_RE.match(segments[-1]):
            return {"id": plain_store_id(segments[-1])}
        raise ValueError("store link must look like https://www.homedepot.com/l/Cumberland/GA/Atlanta/30339/121")
    if _ZIP_RE.match(value):
        return {"zip": value}
    if _STORE_RE.match(value):
        return {"id": plain_store_id(value)}
    raise ValueError("store must be a Home Depot store number (121), a store link or a 5-digit ZIP code")


def resolve_location(value):
    """ZIP, 'City, ST', 'lat,lng', store number or store link ->
    {"zip"} | {"query"} | {"latitude", "longitude"} | {"id"}."""
    value = " ".join(str(value or "").split())
    if not value:
        raise ValueError("location is required")
    if _ZIP_RE.match(value):
        return {"zip": value}
    match = _LATLNG_RE.match(value)
    if match:
        latitude, longitude = float(match.group(1)), float(match.group(2))
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("location coordinates are out of range")
        return {"latitude": latitude, "longitude": longitude}
    if _is_url(value) or _STORE_RE.match(value):
        ref = resolve_store(value)
        return {"id": ref["id"]} if "id" in ref else {"zip": ref["zip"]}
    if value.isdigit():
        raise ValueError("location must be a 5-digit ZIP, 'City, ST', 'latitude,longitude', a store number or a store link")
    if len(value) < 2:
        raise ValueError("location is too short")
    return {"query": value}
