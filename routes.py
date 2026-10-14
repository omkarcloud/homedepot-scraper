"""The 12 Home Depot endpoints. Every path is served with and without the
`/homedepot` prefix, so code generated against the hosted API on RapidAPI
(paths like /products/details) runs unchanged against this server.

Params are validated by the same marshmallow schemas the hosted API uses
(homedepot/schemas.py): unknown params and bad values are a 400."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from homedepot import categories, deals, products, stores
from homedepot import schemas as S
from schema_fields import load_query
from scraper_errors import BadRequest, NotFound


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The request query as unicode strings (bottle 0.12's .get() hands back
    latin-1 decoded bytes, so a UTF-8 "Amélie" would arrive as "AmÃ©lie")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    scheme, netloc = request.urlparts.scheme, request.urlparts.netloc
    return f"{scheme}://{netloc}{path}?{urlencode(query, doseq=True)}"


def paginate(result, path, raw_params):
    """Lift the scraper's `pagination` block into the flat shape the hosted
    API returns: count / per_page / current_page / total_pages / next /
    previous first, then the payload."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = _as_int(pagination.get("page")) or _as_int(raw_params.get("page")) or 1
    total_pages = max(_as_int(pagination.get("total_pages")), 0)
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, raw_params, page + 1 if page < total_pages else None),
        "previous": _page_link(path, raw_params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(path, schema, impl, paginated=False):
    """Shared pipeline: validate -> run -> map errors (bad params -> 400,
    missing entity -> 404, retries exhausted / blocked -> 500)."""
    raw = query_dict()
    data, error = load_query(schema, raw)
    if error:
        return json_response(error, 400)
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"homedepot rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:
        return json_response({"error": f"homedepot {path.strip('/')} failed: {type(e).__name__}: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


ENDPOINTS = [
    ("/products/details", S.ProductSchema, products.details, False),
    ("/products/search", S.SearchSchema, products.search, True),
    ("/products/lookup", S.LookupSchema, products.lookup, False),
    ("/products/bulk", S.ProductsSchema, products.bulk, False),
    ("/products/availability", S.AvailabilitySchema, products.availability, False),
    ("/products/reviews", S.ReviewsSchema, products.reviews, True),
    ("/products/questions", S.QuestionsSchema, products.questions, True),
    ("/categories", S.EmptySchema, categories.departments, False),
    ("/categories/products", S.CategoryProductsSchema, categories.products, True),
    ("/stores/search", S.StoreSearchSchema, stores.search, False),
    ("/stores/details", S.StoreSchema, stores.details, False),
    ("/deals", S.DealsSchema, deals.daily, False),
]


def mount(path, schema, impl, paginated):
    """Serve a handler at /path and /homedepot/path."""
    def handler():
        return call(path, schema, impl, paginated)
    handler.__name__ = "homedepot_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/homedepot" + path, method="GET")(handler)


for _path, _schema, _impl, _paginated in ENDPOINTS:
    mount(_path, _schema, _impl, _paginated)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, *_ in ENDPOINTS]})
