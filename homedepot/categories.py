"""/homedepot/categories/* — the department list and category / brand
browse pages (products + facets + child categories)."""
from homedepot import parsers as P
from homedepot import shared
from homedepot.fetch import HomeDepotNotFound, graphql

DEPARTMENTS_QUERY = "query savingsDepartment { savingsDepartment { departmentCategories { name url image { url } } } }"


def departments():
    """The site's top-level departments (name, browse code, link)."""
    data = graphql("savingsDepartment", DEPARTMENTS_QUERY, {}, root="savingsDepartment")
    rows = [P.department(d) for d in P.listed(data.get("departmentCategories")) if isinstance(d, dict)]
    rows = [r for r in rows if r["name"]]
    return {"count": len(rows), "departments": rows}


def products(category, page=1, sort=None, min_price=None, max_price=None, brands=None, min_rating=None,
             pickup_today=False, store=None):
    located = shared.locate_store(store)
    page_data = shared.listing(located, nav=category, page=page, sort=sort, min_price=min_price,
                               max_price=max_price, brands=brands, min_rating=min_rating, pickup_today=pickup_today)
    if page_data["pagination"]["total_count"] == 0 and not page_data["breadcrumbs"] and not page_data["title"]:
        raise HomeDepotNotFound(f"category '{category}' not found")
    page_data["category"] = {
        "code": category,
        "name": page_data.pop("title") or (page_data["breadcrumbs"][-1]["name"] if page_data["breadcrumbs"] else None),
        "link": page_data.pop("link"),
    }
    page_data["store"] = shared.store_summary(located)
    for key in ("query", "corrected_query", "suggested_query", "translated_from", "redirect_link"):
        page_data.pop(key, None)
    return page_data
