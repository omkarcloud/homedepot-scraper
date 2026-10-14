"""Home Depot normalizers: the federation gateway's camelCase (and
Bazaarvoice PascalCase) objects -> one clean snake_case shape per entity.

Output conventions (shared with the other scrapers here): `link` for page
URLs (always absolute), `image` for pictures, `*_count` for counters,
`is_*`/`has_*` for booleans, ISO-8601 UTC timestamps ("2026-10-13T09:40:29Z")
and ISO dates ("2026-10-14"), numbers as numbers, prices as a numeric
amount next to one `currency` ("USD"), null for missing.

One product shape everywhere (search, browse, lookups, bulk, deals); the
details endpoint adds the long-form blocks to the same object:

  product  {id, name, link, brand, model_number, store_sku, parent_id,
            product_type, image, rating, pricing, badges, availability,
            fulfillment, categories, department, collection, highlights,
            options, is_* flags, quantity_limit, return_policy}
           + details: description, upc, gtin, images, videos, three_sixty,
             specifications, key_features, dimensions, breadcrumbs,
             brand_link, protection_plan_skus, subscription, bundle, seo,
             prop65

Deliberately dropped as noise:
  * tracking / ads — sponsoredMetadata, sponsoredBeacon (isSponsored is
    kept as is_sponsored), dataSource(s), the gateway `id`, templates,
    partialTemplates, discoveryZones, buyitagain, orangeGraph, analytics
    semantic tokens, adBlocker;
  * viewer state — favoriteDetail, loyalty, customerSignal, cart;
  * presentation-only — image size lists (one 1000-px link is emitted, the
    template keeps the sizes), hotspots / ocrHotspots, creativeIconUrl,
    badge colours / timers, swatch "isSelected", alternatePriceDisplay,
    preferredPriceFlag, dimension collapse / visual-nav flags, pricing
    `message` strings that duplicate the structured promotion;
  * duplicates — identifiers.itemId (= itemId), omsThdSku (= store SKU),
    seoDescription (= seo.seoDescription), review RatingRange (always 5),
    OriginalProductName on syndicated reviews, Answer ModerationStatus
    (every served answer is APPROVED), Limit/Offset (the pagination block
    carries them), AnswerIds (the answers are inlined), `__typename`;
  * internal ids — classNumber / subClassNumber, productDepartmentId,
    gccExperienceOmsId, replacementOMSID, sampleId, protection plan SKUs
    are kept (useful), AuthorId / CampaignId on reviews and answers,
    SubmissionId on questions.
"""
import re
from datetime import datetime, timezone

from homedepot import refs

CURRENCY = "USD"

_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_SERVICE_NAMES = {
    "loadNGo": "load_n_go", "propane": "propane", "toolRental": "tool_rental", "penske": "penske_truck_rental",
    "keyCutting": "key_cutting", "wiFi": "wifi", "applianceShowroom": "appliance_showroom",
    "expandedFlooringShowroom": "expanded_flooring_showroom", "largeEquipment": "large_equipment_rental",
    "kitchenShowroom": "kitchen_showroom",
}
_DELIVERY_TYPES = {"sth": "ship_to_home", "bodfs": "scheduled_delivery", "express delivery": "express_delivery",
                   "bopis": "store_pickup", "boss": "ship_to_store"}
_SECONDARY = {"Quality": "quality", "Value": "value", "EnergyEfficiency": "energy_efficiency",
              "Features": "features", "Appearance": "appearance", "EaseOfInstallation": "ease_of_installation",
              "EaseOfUse": "ease_of_use"}
_BADGE_NAMES = {"verifiedPurchaser": "verified_purchaser", "earlyReviewerIncentive": "early_reviewer_incentive",
                "incentivizedReview": "incentivized_review", "diy": "diy", "top250Contributor": "top_250_contributor",
                "top1000Contributor": "top_1000_contributor", "staff": "staff", "expert": "expert"}
_SNAKE_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


# ---- value helpers ------------------------------------------------------------
# (kept local so the package stands alone, like the other site packages)

def to_int(value):
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def to_float(value):
    if isinstance(value, bool):
        return None
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def text(value):
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value or None


def bool_or_none(value):
    return value if isinstance(value, bool) else None


def money(value):
    number = to_float(value)
    return round(number, 2) if number is not None else None


def positive(value):
    """A number that means nothing when 0 / negative (dollar-off, percent-off)."""
    number = to_float(value)
    return round(number, 2) if number else None


def snake(value):
    """'TOP_SELLERS' / 'topRated' / 'Pick Up Today' -> 'top_sellers' ..."""
    if not isinstance(value, str) or not value.strip():
        return None
    out = _SNAKE_RE.sub("_", value.strip())
    out = re.sub(r"[^A-Za-z0-9]+", "_", out).strip("_").lower()
    return out or None


def iso_utc(value):
    """'2026-10-13T09:40:29.000+00:00' / '2022-07-03T06:46:19.938Z' ->
    '2026-10-13T09:40:29Z'."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_date(value):
    """'2026-10-14' / '2026-10-14T00:00:00Z' / '10/14/2026' -> '2026-10-14'."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)
    if match:
        return match.group(0)
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw)
    if match:
        return f"{match.group(3)}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
    return None


def split_csv(value):
    """'AK,GU,HI' -> ['AK', 'GU', 'HI'] ([] if absent)."""
    if not isinstance(value, str):
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def listed(value):
    return [v for v in value if v is not None] if isinstance(value, list) else []


def _dict(value):
    return value if isinstance(value, dict) else {}


# ---- product cards ----------------------------------------------------------------

def rating(raw):
    rr = _dict(_dict(raw).get("ratingsReviews"))
    average = to_float(rr.get("averageRating"))
    count = to_int(rr.get("totalReviews"))
    if average is None and count is None:
        return None
    return {"average": round(average, 2) if average is not None else None, "count": count}


def image(raw):
    raw = _dict(raw)
    link = refs.image_link(raw.get("url"))
    if not link:
        return None
    return {"link": link, "type": snake(raw.get("subType")) or snake(raw.get("type")),
            "alt_text": text(raw.get("altText")), "template": text(raw.get("url"))}


def _primary_image(media):
    images = listed(_dict(media).get("images"))
    primary = next((i for i in images if _dict(i).get("subType") == "PRIMARY"), None) or (images[0] if images else None)
    return refs.image_link(_dict(primary).get("url")) if primary else None


def promotion(raw):
    raw = _dict(raw)
    description = _dict(raw.get("description"))
    dates = _dict(raw.get("dates"))
    out = {
        "type": text(raw.get("type")),
        "tag": text(raw.get("promotionTag")),
        "dollar_off": positive(raw.get("dollarOff")),
        "percent_off": positive(raw.get("percentageOff")),
        "savings_center": text(raw.get("savingsCenter")),
        "savings_center_promos": text(raw.get("savingsCenterPromos")),
        "special_buy_savings": text(raw.get("specialBuySavings")),
        "special_buy_dollar_off": positive(raw.get("specialBuyDollarOff")),
        "special_buy_percent_off": positive(raw.get("specialBuyPercentageOff")),
        "experience": text(raw.get("experienceTag")),
        "sub_experience": text(raw.get("subExperienceTag")),
        "short_description": text(description.get("shortDesc")),
        "long_description": text(description.get("longDesc")),
        "starts_at": iso_date(dates.get("start")),
        "ends_at": iso_date(dates.get("end")),
    }
    return out if any(v is not None for v in out.values()) else None


def conditional_promotion(raw):
    raw = _dict(raw)
    tiers = [{
        "min_threshold": to_float(t.get("minThresholdVal")),
        "threshold_type": snake(t.get("thresholdType")),
        "reward_value": to_float(t.get("rewardVal")),
        "reward_type": snake(t.get("rewardType")),
        "reward_level": text(t.get("rewardLevel")),
        "max_reward_amount": to_float(t.get("maxAllowedRewardAmount")),
    } for t in listed(_dict(raw.get("reward")).get("tiers")) if isinstance(t, dict)]
    criteria = [{
        "item_group": text(c.get("itemGroup")),
        "min_threshold": to_float(c.get("minThresholdVal")),
        "threshold_type": snake(c.get("thresholdType")),
    } for c in listed(raw.get("eligibilityCriteria")) if isinstance(c, dict)]
    return {
        "id": to_int(raw.get("promotionId")),
        "tags": [text(t) for t in listed(raw.get("promotionTags")) if text(t)],
        "item_group": text(raw.get("skuItemGroup")),
        "eligibility": criteria,
        "reward_tiers": tiers,
    }


def pricing(raw):
    raw = _dict(raw)
    price = money(raw.get("value"))
    original = money(raw.get("original"))
    if original is not None and price is not None and original <= price:
        original = None    # "original" equal to the price is not a strike-through
    alternate = _dict(raw.get("alternate"))
    bulk = _dict(alternate.get("bulk"))
    unit = _dict(alternate.get("unit"))
    clearance = _dict(raw.get("clearance"))
    map_detail = _dict(raw.get("mapDetail"))
    discount_amount = round(original - price, 2) if (original is not None and price is not None) else None
    discount_percent = round(discount_amount / original * 100, 1) if (discount_amount and original) else None
    out = {
        "currency": CURRENCY,
        "price": price,
        "original_price": original,
        "discount_amount": discount_amount,
        "discount_percent": discount_percent,
        "unit": text(raw.get("unitOfMeasure")),
        "is_special_buy": bool(raw.get("specialBuy")),
        "is_clearance": bool(clearance.get("value")),
        "is_map_price": bool(map_detail.get("mapPolicy")),
        "is_price_hidden": bool(raw.get("hidePrice")),
        "message": text(raw.get("message")),
        "clearance": {
            "price": money(clearance.get("value")),
            "dollar_off": positive(clearance.get("dollarOff")),
            "percent_off": positive(clearance.get("percentageOff")),
            "unit_price": money(clearance.get("unitsClearancePrice")),
        } if clearance.get("value") is not None else None,
        "bulk": {
            "price_per_unit": money(bulk.get("pricePerUnit")),
            "min_quantity": to_int(bulk.get("thresholdQuantity")),
            "price": money(bulk.get("value")),
        } if bulk.get("pricePerUnit") is not None or bulk.get("value") is not None else None,
        "unit_price": {
            "price": money(unit.get("value")),
            "original_price": money(unit.get("unitsOriginalPrice")),
            "unit": text(unit.get("caseUnitOfMeasure")),
            "units_per_case": to_int(unit.get("unitsPerCase")) or None,
        } if unit.get("value") is not None else None,
        "map": {
            "policy": text(map_detail.get("mapPolicy")),
            "effective_price": money(map_detail.get("effectiveMap")),
            "dollar_off": positive(map_detail.get("dollarOff")),
            "percent_off": positive(map_detail.get("percentageOff")),
            "is_above_original_price": bool_or_none(raw.get("mapAboveOriginalPrice")),
        } if map_detail else None,
        "promotion": promotion(raw.get("promotion")),
        "conditional_promotions": [c for c in (conditional_promotion(c) for c in listed(raw.get("conditionalPromotions"))
                                               if isinstance(c, dict)) if c["id"] is not None or c["reward_tiers"]],
    }
    return out


def _location(raw):
    raw = _dict(raw)
    inventory = _dict(raw.get("inventory"))
    return {
        "store": {
            "id": refs.plain_store_id(raw.get("locationId")) if raw.get("type") == "store" else None,
            "name": text(raw.get("storeName")),
            "phone": text(raw.get("storePhone")),
            "state": text(raw.get("state")),
            "distance_miles": to_float(raw.get("distance")),
        } if raw.get("type") == "store" else None,
        "location_type": text(raw.get("type")),
        "is_anchor": bool_or_none(raw.get("isAnchor")),
        "quantity": to_int(inventory.get("quantity")),
        "is_in_stock": bool_or_none(inventory.get("isInStock")),
        "is_out_of_stock": bool_or_none(inventory.get("isOutOfStock")),
        "is_limited_quantity": bool_or_none(inventory.get("isLimitedQuantity")),
        "is_unavailable": bool_or_none(inventory.get("isUnavailable")),
        "max_pickup_quantity": to_int(inventory.get("maxAllowedBopisQty")),
        "min_pickup_quantity": to_int(inventory.get("minAllowedBopisQty")),
        "has_curbside_pickup": bool_or_none(raw.get("curbsidePickupFlag")),
        "is_check_nearby": bool_or_none(raw.get("isBuyInStoreCheckNearBy")),
    }


def _service(raw, option_type):
    raw = _dict(raw)
    dates = _dict(raw.get("deliveryDates"))
    eta = _dict(raw.get("dynamicEta"))
    kind = text(raw.get("type"))
    locations = [_location(l) for l in listed(raw.get("locations")) if isinstance(l, dict)]
    return {
        "type": _DELIVERY_TYPES.get((kind or "").lower(), snake(kind)),
        "service_code": kind,
        "option": option_type,
        "is_free": bool_or_none(raw.get("hasFreeShipping")),
        "free_delivery_threshold": money(raw.get("freeDeliveryThreshold")),
        "charge": money(raw.get("deliveryCharge")),
        "total_charge": money(raw.get("totalCharge")),
        "timeline": text(raw.get("deliveryTimeline")),
        "message": text(raw.get("deliveryMessage")),
        "earliest_date": iso_date(raw.get("earliestDeliveryDate")),
        "starts_at": iso_date(dates.get("startDate")),
        "ends_at": iso_date(dates.get("endDate")),
        "eta_hours": to_int(eta.get("hours")),
        "eta_minutes": to_int(eta.get("minutes")),
        "locations": locations,
    }


def fulfillment(raw):
    raw = _dict(raw)
    pickup, delivery = [], []
    for option in listed(raw.get("fulfillmentOptions")):
        option = _dict(option)
        option_type = text(option.get("type"))
        for service in listed(option.get("services")):
            parsed = _service(service, option_type)
            parsed["is_fulfillable"] = bool_or_none(option.get("fulfillable"))
            (pickup if (option_type or "").lower() == "pickup" else delivery).append(parsed)
    # Only "bopis" (buy online, pick up in store) is shelf stock at the store;
    # "boss" (ship to store) reports the ONLINE quantity against the store.
    store_pickup = next((s for s in pickup if s["service_code"] == "bopis"), None)
    ship_to_store = next((s for s in pickup if s["service_code"] == "boss"), None)
    anchor = next((l for l in (store_pickup or {}).get("locations", []) if l.get("is_anchor")), None) \
        if store_pickup else None
    if anchor is None and store_pickup and store_pickup["locations"]:
        anchor = store_pickup["locations"][0]
    boss_location = (ship_to_store or {}).get("locations", [None])[0] if ship_to_store and ship_to_store["locations"] else None
    online = next((l for s in delivery for l in s["locations"] if l["location_type"] == "online"), None)
    return {
        "pickup": {
            "is_available": bool(store_pickup and store_pickup.get("is_fulfillable")),
            "store": anchor["store"] if anchor else ((boss_location or {}).get("store") if boss_location else None),
            "quantity": anchor["quantity"] if anchor else (0 if ship_to_store else None),
            "is_in_stock": anchor["is_in_stock"] if anchor else (False if ship_to_store else None),
            "is_limited_quantity": anchor["is_limited_quantity"] if anchor else None,
            "has_curbside_pickup": anchor["has_curbside_pickup"] if anchor else None,
            "max_quantity": anchor["max_pickup_quantity"] if anchor else None,
            "is_ship_to_store_available": bool(ship_to_store and ship_to_store.get("is_fulfillable")),
            "options": pickup,
        },
        "delivery": {
            "is_available": any(s.get("is_fulfillable") for s in delivery),
            "online_quantity": online["quantity"] if online else None,
            "options": delivery,
        },
        "is_backordered": bool_or_none(raw.get("backordered")),
        "backordered_ship_date": iso_date(raw.get("backorderedShipDate")),
        "excluded_ship_states": split_csv(raw.get("excludedShipStates")),
        "excluded_ship_to_store_states": split_csv(raw.get("bossExcludedShipStates")),
        "is_store_active": bool_or_none(raw.get("anchorStoreStatus")),
        "store_status": text(raw.get("anchorStoreStatusType")),
        "is_online_active": bool_or_none(raw.get("onlineStoreStatus")),
        "online_status": text(raw.get("onlineStoreStatusType")),
        "is_seasonal": bool_or_none(raw.get("seasonStatusEligible")),
    }


def swatch(raw):
    raw = _dict(raw)
    return {
        "item_id": text(raw.get("itemId")),
        "label": text(raw.get("label")),
        "value": text(raw.get("value")),
        "link": refs.absolute_link(raw.get("url")),
        "image": refs.absolute_link(raw.get("swatchImgUrl")),
    }


def product_card(raw):
    """One list product (searchModel.products[])."""
    raw = _dict(raw)
    ident = _dict(raw.get("identifiers"))
    info = _dict(raw.get("info"))
    details = _dict(raw.get("details"))
    collection = _dict(details.get("collection"))
    availability = _dict(raw.get("availabilityType"))
    item_id = text(raw.get("itemId")) or text(ident.get("itemId"))
    crumbs = [text(_dict(b).get("label")) for b in listed(_dict(raw.get("taxonomy")).get("breadCrumbs"))]
    categories = [c for c in (listed(info.get("categoryHierarchy")) or crumbs) if c]
    price = pricing(raw.get("pricing"))
    price["is_price_hidden"] = bool(info.get("hidePrice"))
    return {
        "id": item_id,
        "name": text(ident.get("productLabel")),
        "link": refs.product_link(item_id, ident.get("canonicalUrl")),
        "brand": text(ident.get("brandName")),
        "model_number": text(ident.get("modelNumber")),
        "store_sku": text(ident.get("storeSkuNumber")),
        "parent_id": text(ident.get("parentId")) if text(ident.get("parentId")) != item_id else None,
        "product_type": snake(ident.get("productType")),
        "image": _primary_image(raw.get("media")),
        "rating": rating(raw.get("reviews")),
        "pricing": price,
        "badges": [text(_dict(b).get("label")) or text(_dict(b).get("name")) for b in listed(raw.get("badges"))
                   if text(_dict(b).get("label")) or text(_dict(b).get("name"))],
        "availability": {
            "is_buyable": bool_or_none(availability.get("buyable")),
            "is_discontinued": bool_or_none(availability.get("discontinued")),
            "type": text(availability.get("type")),
        },
        "fulfillment": fulfillment(raw.get("fulfillment")),
        "categories": categories,
        "department": text(info.get("productDepartment")),
        "sub_type": {"name": text(_dict(info.get("productSubType")).get("name")),
                     "link": refs.absolute_link(_dict(info.get("productSubType")).get("link"))}
        if _dict(info.get("productSubType")).get("name") else None,
        "collection": {"id": text(collection.get("collectionId")), "name": text(collection.get("name")),
                       "link": refs.absolute_link(collection.get("url"))} if collection.get("name") else None,
        "highlights": [text(h) for h in listed(details.get("highlights")) if text(h)],
        "options": {
            "count": to_int(info.get("totalNumberOfOptions")),
            "swatches": [swatch(s) for s in listed(info.get("swatches")) if isinstance(s, dict)],
        },
        "has_variants": bool(ident.get("isSuperSku")) or bool(to_int(info.get("totalNumberOfOptions"))),
        "is_special_order": bool(ident.get("specialOrderSku")),
        "is_bundle": bool(raw.get("bundleFlag")),
        "is_sponsored": bool(info.get("isSponsored")),
        "is_live_goods": bool(info.get("isLiveGoodsProduct")),
        "is_generic": bool(info.get("isGenericProduct")),
        "has_subscription": bool(info.get("hasSubscription")),
        "has_eco_rebate": bool(info.get("ecoRebate")),
        "quantity_limit": to_int(info.get("quantityLimit")) or None,
        "return_policy": text(info.get("returnable")),
    }


# ---- product details ------------------------------------------------------------------

def video(raw):
    raw = _dict(raw)
    link = _dict(raw.get("link"))
    return {
        "id": text(raw.get("videoId")),
        "title": text(raw.get("title")),
        "type": text(raw.get("type")),
        "link": refs.absolute_link(raw.get("url")),
        "thumbnail": refs.absolute_link(raw.get("thumbnail") or raw.get("videoStill")),
        "description": text(raw.get("shortDescription")) or text(raw.get("longDescription")),
        "uploaded_at": iso_utc(raw.get("uploadDate")),
        "modified_at": iso_utc(raw.get("dateModified")),
        "more_link": refs.absolute_link(link.get("url")),
    }


def specifications(raw):
    """[{specTitle, specifications[{specName, specValue}]}] ->
    [{group, specs: [{name, value}]}]."""
    out = []
    for group in listed(raw):
        group = _dict(group)
        specs = [{"name": text(_dict(s).get("specName")), "value": text(_dict(s).get("specValue"))}
                 for s in listed(group.get("specifications")) if text(_dict(s).get("specName"))]
        if specs:
            out.append({"group": text(group.get("specTitle")), "specs": specs})
    return out


def key_features(raw):
    out = []
    for item in listed(_dict(raw).get("keyProductFeaturesItems")):
        for feature in listed(_dict(item).get("features")):
            feature = _dict(feature)
            if text(feature.get("name")):
                out.append({"name": text(feature.get("name")), "value": text(feature.get("value")),
                            "link": refs.absolute_link(feature.get("refinementUrl"))})
    return out


def dimensions(raw):
    out = []
    for group in listed(_dict(raw).get("attributeGroups")):
        group = _dict(group)
        out.append({
            "label": text(group.get("dimensionLabel")),
            "product_type": text(group.get("productType")),
            "attributes": [{"name": text(_dict(a).get("attributeName")),
                            "values": [text(v) for v in listed(_dict(a).get("dimensions")) if text(v)]}
                           for a in listed(group.get("attributes")) if text(_dict(a).get("attributeName"))],
        })
    return out


def breadcrumb(raw):
    raw = _dict(raw)
    path = raw.get("browseUrl") or raw.get("url")
    return {"name": text(raw.get("label")), "link": refs.absolute_link(path), "code": refs.category_code(path)}


def product_details(raw):
    """The product page record (productClientOnlyProduct.product): the card
    plus the long-form blocks."""
    raw = _dict(raw)
    out = product_card(raw)
    ident = _dict(raw.get("identifiers"))
    info = _dict(raw.get("info"))
    media = _dict(raw.get("media"))
    details = _dict(raw.get("details"))
    seo = _dict(raw.get("seo"))
    subscription = _dict(raw.get("subscription"))
    bundle = _dict(raw.get("bundleSpecificationDetails"))
    taxonomy = _dict(raw.get("taxonomy"))
    installation = _dict(details.get("installation"))
    three_sixty = _dict(media.get("threeSixty"))
    ar = _dict(media.get("augmentedRealityLink"))
    out.update({
        "description": text(details.get("description")),
        "upc": text(ident.get("upc")),
        "gtin": text(ident.get("upcGtin13")),
        "sku_classification": text(ident.get("skuClassification")),
        "brand_link": refs.absolute_link(ident.get("brandMainPageUrl")),
        "images": [i for i in (image(m) for m in listed(media.get("images"))) if i],
        "videos": [video(v) for v in listed(media.get("video")) if isinstance(v, dict)],
        "three_sixty": {"id": text(three_sixty.get("id")), "link": refs.absolute_link(three_sixty.get("url"))}
        if three_sixty.get("url") else None,
        "augmented_reality": {"usdz_link": refs.absolute_link(ar.get("usdz")), "image": refs.absolute_link(ar.get("image"))}
        if ar.get("usdz") or ar.get("image") else None,
        "specifications": specifications(raw.get("specificationGroup")),
        "key_features": key_features(raw.get("keyProductFeatures")),
        "dimensions": dimensions(raw.get("sizeAndFitDetail")),
        "breadcrumbs": [breadcrumb(b) for b in listed(taxonomy.get("breadCrumbs")) if text(_dict(b).get("label"))],
        "category_link": refs.absolute_link(taxonomy.get("brandLinkUrl")),
        "badges_detail": [{"name": text(_dict(b).get("label")) or text(_dict(b).get("name")),
                           "message": text(_dict(b).get("message")), "ends_at": iso_date(_dict(b).get("endDate")),
                           "image": refs.absolute_link(_dict(b).get("creativeImageUrl"))}
                          for b in listed(raw.get("badges")) if isinstance(b, dict)],
        "installation": {"service_type": text(installation.get("serviceType")),
                         "lead_link": refs.absolute_link(installation.get("leadGenUrl"))}
        if installation.get("serviceType") else None,
        "subscription": {"is_available": bool(subscription.get("subscriptionEnabled")),
                         "default_frequency": text(subscription.get("defaultfrequency")),
                         "discount_percent": to_float(subscription.get("discountPercentage"))}
        if subscription else None,
        "bundle": {
            "type": text(bundle.get("type")),
            "experience_type": text(bundle.get("experienceType")),
            "parent_ids": [text(_dict(p).get("parentId")) for p in listed(bundle.get("parents")) if text(_dict(p).get("parentId"))],
            "items": [{"id": text(_dict(i).get("id")), "quantity": to_int(_dict(i).get("quantity"))}
                      for i in listed(raw.get("bundleItems")) if text(_dict(i).get("id"))],
        } if (bundle.get("parents") or raw.get("bundleItems") or bundle.get("type")) else None,
        "protection_plan_skus": split_csv(info.get("eligibleProtectionPlanSkus")) or
        ([text(info.get("protectionPlanSku"))] if text(info.get("protectionPlanSku")) else []),
        "prop65": {"has_warning": bool(info.get("prop65Warning")), "message": text(info.get("prop65Message"))},
        "is_professional_use_only": bool(info.get("forProfessionalUseOnly")),
        "has_augmented_reality": bool(info.get("augmentedReality")),
        "has_visually_similar": bool(info.get("hasVisuallySimilar")),
        "is_bath_renovation": bool(info.get("bathRenovation")),
        "minimum_order_quantity": to_int(info.get("minimumOrderQuantity")) or None,
        "replacement_item_id": text(info.get("replacementOMSID")),
        "paint": {"brand": text(info.get("paintBrand")), "family": text(info.get("paintFamily"))}
        if text(info.get("paintBrand")) or text(info.get("paintFamily")) else None,
        "coverage": {
            "unit": text(info.get("unitOfMeasureCoverage")),
            "units_per_item": to_float(_dict(info.get("pipCalculator")).get("coverageUnits")),
            "has_calculator": bool(_dict(info.get("pipCalculator")).get("display")) or bool(info.get("projectCalculatorEligible")),
        } if text(info.get("unitOfMeasureCoverage")) or _dict(info.get("pipCalculator")).get("coverageUnits") else None,
        "price_range": {"min": money(info.get("wasMinPriceRange")), "max": money(info.get("wasMaxPriceRange"))}
        if info.get("wasMinPriceRange") is not None or info.get("wasMaxPriceRange") is not None else None,
        "rental": {"sku": text(ident.get("toolRentalSkuNumber")), "category": text(ident.get("rentalCategory")),
                   "sub_category": text(ident.get("rentalSubCategory"))}
        if text(ident.get("toolRentalSkuNumber")) else None,
        "seo": {"keywords": text(seo.get("seoKeywords")), "description": text(seo.get("seoDescription"))},
    })
    return out


# ---- search facets / navigation ----------------------------------------------------------

def refinement(raw):
    raw = _dict(raw)
    return {
        "name": text(raw.get("label")),
        "key": text(raw.get("refinementKey")),
        "count": to_int(raw.get("recordCount")),
        "is_selected": bool(raw.get("selected")),
        "link": refs.absolute_link(raw.get("url")),
        "image": refs.absolute_link(raw.get("imgUrl")),
        "children": [refinement(n) for n in listed(raw.get("nestedRefinements")) if isinstance(n, dict)] or None,
    }


def facet(raw):
    raw = _dict(raw)
    return {
        "name": text(raw.get("label")),
        "id": text(raw.get("dimensionId")),
        "is_numeric": bool(raw.get("isNumericFilter")),
        "is_color_swatch": bool(raw.get("isColorSwatch")),
        "values": [refinement(r) for r in listed(raw.get("refinements")) if isinstance(r, dict)],
    }


def applied_facet(raw):
    raw = _dict(raw)
    return {
        "name": text(raw.get("label")),
        "values": [{"name": text(_dict(r).get("label")), "key": text(_dict(r).get("refinementKey")),
                    "remove_link": refs.absolute_link(_dict(r).get("url"))}
                   for r in listed(raw.get("refinements")) if isinstance(r, dict)],
    }


def child_category(raw):
    raw = _dict(raw)
    link = text(raw.get("webUrl"))
    return {"name": text(raw.get("label")), "id": text(raw.get("categoryId")), "code": refs.category_code(link),
            "link": refs.absolute_link(link)}


def search_page(raw):
    """searchModel -> {query, corrected_query, suggested_query, canonical_link,
    title, store, in_store_count, breadcrumbs, categories, related_searches,
    applied_filters, filters, products, pagination}."""
    raw = _dict(raw)
    report = _dict(raw.get("searchReport"))
    meta = _dict(raw.get("metadata"))
    taxonomy = _dict(raw.get("taxonomy"))
    related = _dict(raw.get("relatedResults"))
    store = _dict(meta.get("stores"))
    return {
        "query": text(report.get("keyword")),
        "corrected_query": text(report.get("correctedKeyword")),
        "suggested_query": text(report.get("didYouMean")),
        "translated_from": text(report.get("translatedFrom")),
        "title": text(meta.get("h1Tag")),
        "link": refs.absolute_link(meta.get("canonicalUrl") or report.get("searchUrl")),
        "redirect_link": refs.absolute_link(meta.get("searchRedirect")),
        "page_type": text(meta.get("contentType")),
        "category_id": text(meta.get("categoryID")),
        "store": {"id": refs.plain_store_id(store.get("storeId")), "name": text(store.get("storeName")),
                  "zip": text(_dict(store.get("address")).get("postalCode"))} if store.get("storeId") else None,
        "in_store_count": to_int(_dict(meta.get("productCount")).get("inStore")),
        "breadcrumbs": [breadcrumb(b) for b in listed(taxonomy.get("breadCrumbs")) if text(_dict(b).get("label"))],
        "brand_link": refs.absolute_link(taxonomy.get("brandLinkUrl")),
        "categories": [child_category(v) for v in listed(related.get("visualNavs")) if text(_dict(v).get("label"))],
        "related_searches": [text(_dict(k).get("keyword")) for k in listed(related.get("relatedKeywords"))
                             if text(_dict(k).get("keyword"))],
        "applied_filters": [applied_facet(a) for a in listed(raw.get("appliedDimensions")) if isinstance(a, dict)],
        "filters": [facet(d) for d in listed(raw.get("dimensions")) if isinstance(d, dict)],
        "products": [product_card(p) for p in listed(raw.get("products")) if isinstance(p, dict)],
        "total": to_int(report.get("totalProducts")),
    }


def pagination(page, page_size, total, max_pages=None):
    total = total or 0
    total_pages = (total + page_size - 1) // page_size if page_size else 0
    if max_pages:
        total_pages = min(total_pages, max_pages)
    return {"page": page, "items_per_page": page_size, "total_pages": total_pages, "total_count": total}


# ---- stock -------------------------------------------------------------------------------

def _unpad(value):
    """'08' -> '8', '015' -> '15'; 'EC1' stays."""
    value = text(value)
    if value and value.isdigit():
        return str(int(value))
    return value


def aisle_bay(raw):
    """aislebay.storeSkus[] -> {store sku: {aisle, bay, label}}."""
    out = {}
    for row in listed(_dict(raw).get("storeSkus")):
        row = _dict(row)
        info = _dict(row.get("aisleBayInfo"))
        sku = text(row.get("storeSkuId"))
        if sku and (info.get("aisle") or info.get("bay")):
            out[sku] = {"aisle": _unpad(info.get("aisle")), "bay": _unpad(info.get("bay")),
                        "label": text(info.get("invLocDescFriendly")) or text(info.get("invLocDesc"))}
    return out


# ---- reviews ------------------------------------------------------------------------------

def _photo(raw):
    raw = _dict(raw)
    sizes = _dict(raw.get("Sizes"))
    link = refs.absolute_link(_dict(sizes.get("normal")).get("Url"))
    if not link:
        return None
    return {"id": text(raw.get("Id")), "link": link, "thumbnail": refs.absolute_link(_dict(sizes.get("thumbnail")).get("Url")),
            "caption": text(raw.get("Caption"))}


def review(raw):
    raw = _dict(raw)
    badges = [_BADGE_NAMES.get(b, snake(b)) for b in listed(raw.get("BadgesOrder")) if isinstance(b, str)]
    secondary = {}
    for key, name in _SECONDARY.items():
        value = _dict(_dict(raw.get("SecondaryRatings")).get(key))
        if value.get("Value") is not None:
            secondary[name] = to_float(value.get("Value"))
    syndication = _dict(raw.get("SyndicationSource"))
    tags = _dict(raw.get("TagDimensions"))
    context = _dict(raw.get("ContextDataValues"))
    return {
        "id": text(raw.get("Id")),
        "title": text(raw.get("Title")),
        "text": text(raw.get("ReviewText")),
        "rating": to_int(raw.get("Rating")),
        "secondary_ratings": secondary or None,
        "is_recommended": bool_or_none(raw.get("IsRecommended")),
        "is_verified_purchase": "verified_purchaser" in badges
        or str(_dict(context.get("VerifiedPurchaser")).get("Value")).lower() == "true",
        "is_syndicated": bool(raw.get("IsSyndicated")),
        "badges": badges,
        "author": {"name": text(raw.get("UserNickname")), "location": text(raw.get("UserLocation")),
                   "age": text(_dict(context.get("Age")).get("ValueLabel")) or text(_dict(context.get("Age")).get("Value"))},
        "submitted_at": iso_utc(raw.get("SubmissionTime")),
        "helpful_count": to_int(raw.get("TotalPositiveFeedbackCount")),
        "not_helpful_count": to_int(raw.get("TotalNegativeFeedbackCount")),
        "pros": [text(v) for v in listed(_dict(tags.get("Pro")).get("Values")) if text(v)],
        "cons": [text(v) for v in listed(_dict(tags.get("Con")).get("Values")) if text(v)],
        "photos": [p for p in (_photo(x) for x in listed(raw.get("Photos"))) if p],
        "videos": [{"id": text(_dict(v).get("VideoId")), "link": refs.absolute_link(_dict(v).get("VideoUrl")),
                    "thumbnail": refs.absolute_link(_dict(v).get("VideoThumbnailUrl")), "caption": text(_dict(v).get("Caption"))}
                   for v in listed(raw.get("Videos")) if isinstance(v, dict)],
        "responses": [{"text": text(_dict(r).get("Response")), "department": text(_dict(r).get("Department")),
                       "source": text(_dict(r).get("ResponseSource")), "date": iso_utc(_dict(r).get("Date")) or iso_date(_dict(r).get("Date"))}
                      for r in listed(raw.get("ClientResponses")) if isinstance(r, dict)],
        "syndication_source": {"name": text(syndication.get("Name")), "link": refs.absolute_link(syndication.get("ContentLink")),
                               "logo": refs.absolute_link(syndication.get("LogoImageUrl"))}
        if syndication.get("Name") else None,
    }


def review_statistics(raw):
    """reviews.Includes.Products.store.FilteredReviewStatistics -> rating block."""
    stats = _dict(_dict(_dict(_dict(_dict(raw).get("Includes")).get("Products")).get("store")).get("FilteredReviewStatistics"))
    if not stats:
        return None
    histogram = {str(to_int(_dict(d).get("RatingValue"))): to_int(_dict(d).get("Count")) or 0
                 for d in listed(stats.get("RatingDistribution")) if to_int(_dict(d).get("RatingValue"))}
    recommended = to_int(stats.get("RecommendedCount"))
    not_recommended = to_int(stats.get("NotRecommendedCount"))
    answered = (recommended or 0) + (not_recommended or 0)
    return {
        "average": to_float(stats.get("AverageOverallRating")),
        "count": to_int(stats.get("TotalReviewCount")),
        "recommended_count": recommended,
        "not_recommended_count": not_recommended,
        "recommended_percent": round(recommended / answered * 100, 1) if answered and recommended is not None else None,
        "distribution": {star: histogram.get(star, 0) for star in ("5", "4", "3", "2", "1")},
        "secondary_rating_names": [snake(n) for n in listed(stats.get("SecondaryRatingsAveragesOrder")) if snake(n)],
    }


# ---- questions ----------------------------------------------------------------------------

def answer(raw):
    raw = _dict(raw)
    return {
        "id": text(raw.get("Id")),
        "text": text(raw.get("AnswerText")),
        "author": text(raw.get("UserNickname")),
        "is_brand_answer": bool(raw.get("IsBrandAnswer")),
        "is_featured": bool(raw.get("IsFeatured")),
        "badges": [_BADGE_NAMES.get(b, snake(b)) for b in listed(raw.get("BadgesOrder")) if isinstance(b, str)],
        "helpful_count": to_int(raw.get("TotalPositiveFeedbackCount")),
        "answered_at": iso_utc(raw.get("LastModificationTime")) or iso_utc(raw.get("LastModeratedTime")),
        "photos": [p for p in (_photo(x) for x in listed(raw.get("Photos"))) if p],
    }


def question(raw, answers_by_id):
    raw = _dict(raw)
    answers = [answers_by_id[a] for a in listed(raw.get("AnswerIds")) if a in answers_by_id]
    return {
        "id": text(raw.get("Id")),
        "text": text(raw.get("QuestionSummary")),
        "details": text(raw.get("QuestionDetails")),
        "author": text(raw.get("UserNickname")),
        "asked_at": iso_utc(raw.get("SubmissionTime")),
        "answer_count": to_int(raw.get("TotalAnswerCount")) or 0,
        "answers": answers,
        "photos": [p for p in (_photo(x) for x in listed(raw.get("Photos"))) if p],
    }


def questions_page(raw):
    raw = _dict(raw)
    answers_by_id = {}
    for row in listed(_dict(raw.get("Includes")).get("Answers")):
        row = _dict(row)
        parsed = answer(row.get("Answer"))
        key = text(row.get("AnswerId")) or parsed["id"]
        if key:
            answers_by_id[key] = parsed
    return {
        "total": to_int(raw.get("TotalResults")) or 0,
        "questions": [question(q, answers_by_id) for q in listed(raw.get("Results")) if isinstance(q, dict)],
    }


# ---- stores ----------------------------------------------------------------------------------

def store(raw):
    raw = _dict(raw)
    address = _dict(raw.get("address"))
    coords = _dict(raw.get("coordinates"))
    hours = _dict(raw.get("storeHours"))
    services = _dict(raw.get("services"))
    return {
        "id": refs.plain_store_id(raw.get("storeId")),
        "number": refs.pad_store_id(raw.get("storeId")),
        "name": text(raw.get("name")),
        "link": refs.store_link(raw.get("storeDetailsPageLink")),
        "type": text(raw.get("storeType")),
        "address": {
            "street": text(address.get("street")),
            "city": text(address.get("city")),
            "state": text(address.get("state")),
            "zip": text(address.get("postalCode")),
            "country": text(address.get("country")),
        },
        "latitude": to_float(coords.get("lat")),
        "longitude": to_float(coords.get("lng")),
        "distance_miles": to_float(raw.get("distance")),
        "phone": text(raw.get("phone")),
        "pro_desk_phone": text(raw.get("proDeskPhone")),
        "tool_rental_phone": text(raw.get("toolRentalPhone")),
        "hours": {day: {"opens_at": text(_dict(hours.get(day)).get("open")), "closes_at": text(_dict(hours.get(day)).get("close"))}
                  for day in _DAYS if _dict(hours.get(day)).get("open")} or None,
        "services": {public: bool(services.get(key)) for key, public in _SERVICE_NAMES.items()} if services else None,
    }


def suggested_address(raw):
    raw = _dict(raw)
    coords = _dict(raw.get("coordinates"))
    return {"name": text(raw.get("name")), "latitude": to_float(coords.get("lat")), "longitude": to_float(coords.get("lng"))}


# ---- deals / departments -----------------------------------------------------------------------

def deal_group(raw):
    raw = _dict(raw)
    return {
        "name": text(raw.get("name")),
        "tagline": text(raw.get("tagline")),
        "image": refs.image_link(_dict(raw.get("image")).get("url")),
        "item_ids": [text(i) for i in listed(raw.get("itemIds")) if text(i)],
    }


def department(raw):
    raw = _dict(raw)
    link = refs.absolute_link(raw.get("url"))
    code = refs.category_code(link)
    base = code[:-2] if code and code.endswith("Z7") else code     # "Z7" = the Special Values refinement
    return {
        "name": text(raw.get("name")),
        "code": base,
        "link": f"{refs.SITE}/b/{base}" if base else link,
        "deals_code": code,
        "deals_link": link,
        "image": refs.absolute_link(_dict(raw.get("image")).get("url")),
    }
