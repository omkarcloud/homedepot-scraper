"""Marshmallow request schemas for every /homedepot/* route. Generic fields
come from the shared schema_fields.py; this module adds the Home Depot
resolvers. Every schema's load() output is the kwargs dict its endpoint
function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    product    an item id / internet number (320326787) OR a homedepot.com product link
    products   comma-separated item ids and/or links (max 25)
    category   a browse code (N-5yc1vZc27f) OR a homedepot.com /b/ link (brand pages too)
    store      a store number (121), a store link OR a 5-digit ZIP (its nearest store)
    location   a ZIP, "City, ST", "latitude,longitude", a store number or a store link
"""
from marshmallow import ValidationError

from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, LimitField, PageField,
                           PositiveInt, Price, QueryField, RefField, StrippedString)
from homedepot import refs
from homedepot import shared

# public sort value -> the gateway's ProductSort
SORTS = {
    "relevance": {"field": "BEST_MATCH", "order": "ASC"},
    "price_asc": {"field": "PRICE", "order": "ASC"},
    "price_desc": {"field": "PRICE", "order": "DESC"},
    "top_sellers": {"field": "TOP_SELLERS", "order": "ASC"},
    "top_rated": {"field": "TOP_RATED", "order": "ASC"},
    "newest": {"field": "NEW_ITEMS", "order": "ASC"},
}
REVIEW_SORTS = {"most_helpful": "mosthelpfull", "newest": "newest", "oldest": "oldest",
                "highest_rating": "highestrating", "lowest_rating": "lowestrating", "with_photos": "photoreview"}
QUESTION_SORTS = {"newest": "newest", "oldest": "oldest"}
# public store service -> the locator's StoreFeaturesFilter key
SERVICES = {"tool_rental": "toolRental", "propane": "propane", "key_cutting": "keyCutting", "wifi": "wiFi",
            "load_n_go": "loadNGo", "penske_truck_rental": "penske", "appliance_showroom": "applianceShowroom",
            "expanded_flooring_showroom": "expandedFlooringShowroom"}
STAR_RATINGS = ["1", "2", "3", "4", "5"]


def _max_length(n):
    """validate.Length(max=n) that tolerates the None StrippedString returns
    for an empty value (marshmallow runs validators on it; len(None) is a 500)."""
    def check(value):
        if value is not None and len(value) > n:
            raise ValidationError(f"Longer than maximum length {n}.")
    return check


# ---- id-or-link fields -----------------------------------------------------------

class ProductField(RefField):
    resolver = staticmethod(refs.resolve_product)


class ProductListField(RefField):
    resolver = staticmethod(refs.resolve_products)


class CategoryField(RefField):
    resolver = staticmethod(refs.resolve_category)


class StoreField(RefField):
    """Optional everywhere but /stores/details: None = the default store."""
    resolver = staticmethod(refs.resolve_store)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        if not kwargs["required"]:
            kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)


class LocationField(RefField):
    resolver = staticmethod(refs.resolve_location)


def _sort(default="relevance"):
    return ChoiceField(SORTS, load_default=SORTS[default])


class ListingSchema(BaseSchema):
    """The filters every product listing (search, category / brand browse) takes."""
    page = PageField(max_page=shared.MAX_PAGE)
    sort = _sort()
    min_price = Price()
    max_price = Price()
    brands = CommaListField(upper=False, max_items=10)
    min_rating = PositiveInt(max_value=5)
    pickup_today = Flag(load_default=False)
    store = StoreField()


# ---- schemas -----------------------------------------------------------------------

class EmptySchema(BaseSchema):
    pass


class SearchSchema(ListingSchema):
    query = QueryField(max_length=200)


class LookupSchema(BaseSchema):
    """A model number, UPC / GTIN, store SKU or internet number."""
    query = QueryField(max_length=60)
    store = StoreField()


class ProductSchema(BaseSchema):
    product = ProductField()
    store = StoreField()


class ProductsSchema(BaseSchema):
    products = ProductListField()
    store = StoreField()


class AvailabilitySchema(BaseSchema):
    product = ProductField()
    location = LocationField(required=False, load_default=None)
    limit = LimitField(default=5, max_size=20)


class ReviewsSchema(BaseSchema):
    product = ProductField()
    page = PageField(max_page=1000)
    sort = ChoiceField(REVIEW_SORTS, load_default=REVIEW_SORTS["most_helpful"])
    ratings = CommaListField(allowed=STAR_RATINGS, max_items=5)
    verified_only = Flag(load_default=False)
    search = StrippedString(required=False, load_default=None, validate=_max_length(100))


class QuestionsSchema(BaseSchema):
    product = ProductField()
    page = PageField(max_page=500)
    limit = LimitField(default=10, max_size=30)
    sort = ChoiceField(QUESTION_SORTS, load_default=QUESTION_SORTS["newest"])
    search = StrippedString(required=False, load_default=None, validate=_max_length(100))


class CategoryProductsSchema(ListingSchema):
    category = CategoryField()


class StoreSearchSchema(BaseSchema):
    location = LocationField()
    limit = LimitField(default=10, max_size=40)
    services = CommaListField(value_map=SERVICES, max_items=len(SERVICES))


class StoreSchema(BaseSchema):
    store = StoreField(required=True)


class DealsSchema(BaseSchema):
    store = StoreField()
