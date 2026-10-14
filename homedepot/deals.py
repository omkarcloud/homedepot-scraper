"""/homedepot/deals — today's Special Buy of the Day event: its groups
(New Featured Deals, Popular Picks, Top Rated, ...) with their products
priced for the caller's store."""
from homedepot import parsers as P
from homedepot import queries as Q
from homedepot import shared
from homedepot.fetch import graphql


def daily(store=None):
    located = shared.locate_store(store)
    meta = graphql("specialBuyMetadata", Q.SPECIAL_BUY % "DAY", {}, root="specialBuyMetadata")
    groups = [P.deal_group(g) for g in P.listed(meta.get("categoryMetadata")) if isinstance(g, dict)]
    groups = [g for g in groups if g["item_ids"] and not (g["name"] or "").lower().startswith("backup")]
    all_ids = []
    for group in groups:
        all_ids.extend(i for i in group["item_ids"] if i not in all_ids)
    cards = {c["id"]: c for c in shared.items_batched(located, all_ids)}
    out_groups = []
    for group in groups:
        products = [cards[i] for i in group.pop("item_ids") if i in cards]
        out_groups.append({**group, "count": len(products), "products": products})
    return {
        "store": shared.store_summary(located),
        "starts_at": P.iso_date(meta.get("startDate")),
        "ends_at": P.iso_date(meta.get("endDate")),
        "tagline": P.text(meta.get("tagline")),
        "count": sum(g["count"] for g in out_groups),
        "groups": out_groups,
    }
