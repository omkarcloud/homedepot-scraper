"""/homedepot/stores/* — the store locator (stores near a ZIP, city, point
or store number; hours, services, phones, coordinates) and one store."""
from homedepot import shared


def search(location, limit=10, services=None):
    found = shared.stores_near(location, limit=limit, services=services)
    return {
        "searched": found.get("searched"),
        "suggestions": found.get("suggestions") or [],
        "count": len(found["stores"]),
        "stores": found["stores"],
    }


def details(store):
    located = shared.locate_store(store)
    return {"store": located}
