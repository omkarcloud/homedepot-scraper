"""Cache TTL per /homedepot/* endpoint (cache.py, keyed on the validated
params).

Home Depot reprices and re-promotes daily (special buys roll over at
midnight ET); store stock moves through the day; reviews and questions
accrue slowly; the store directory is static.
"""
from datetime import timedelta

# --- products ----------------------------------------------------------------
SEARCH_CACHE = timedelta(hours=1)       # prices + stock flags for 24 products
BROWSE_CACHE = timedelta(hours=1)
LOOKUP_CACHE = timedelta(hours=1)
PRODUCT_CACHE = timedelta(hours=1)
BULK_CACHE = timedelta(minutes=30)
AVAILABILITY_CACHE = timedelta(minutes=15)   # shelf stock at nearby stores
REVIEWS_CACHE = timedelta(hours=12)
QUESTIONS_CACHE = timedelta(hours=12)

# --- catalogue / deals -------------------------------------------------------
DEPARTMENTS_CACHE = timedelta(days=1)
DEALS_CACHE = timedelta(hours=1)

# --- stores ------------------------------------------------------------------
STORES_CACHE = timedelta(days=1)
STORE_CACHE = timedelta(days=1)
