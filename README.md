# Home Depot Scraper API

Search Home Depot products, get full product details with pricing, specs, store availability, and delivery options — all via a simple REST API. 25 free requests/month.

## Key Features

- Search Home Depot products, get full product details with pricing, specs, availability, and store pickup info — all via 1 API.
- 25 free queries per month. No credit card required.

Here's a sample response for a **product search results page**:
```json
{
  "item_id": "334894519",
  "name": "Benning 52 in. Indoor Matte Black Downrod Mount Ceiling Fan with Adjustable White Light LED and Remote Control Included",
  "url": "https://apionline.homedepot.com/p/Hampton-Bay-Benning-52-in-Indoor-Matte-Black-Downrod-Mount-Ceiling-Fan-with-Adjustable-White-Light-LED-and-Remote-Control-Included-85251/334894519",
  "model_number": "85251",
  "pricing": {
    "current_price": 99.0
  },
  "avg_rating": 4.5444,
  "review_count": 169,
  "brand": "Hampton Bay",
  "delivery": {
    "is_free": true
  },
  "pickup": {
    "stock_count": 24,
    "store": "Bangor"
  }
}
```
## ▶️ Video Tutorial

Watch the complete API walkthrough:

[![HomeDepot Scraper API Walkthrough](https://raw.githubusercontent.com/omkarcloud/homedepot-scraper/master/homedepot-scraper-youtube-video-preview.png)](https://www.youtube.com/watch?v=AxgN35LwfW4)

## Get API Key

Create an account at [omkar.cloud](https://www.omkar.cloud/auth/sign-up?redirect=/api-key) to get your API key.

It takes just 2 minutes to sign up. You get 25 free requests every month for detailed Home Depot data.

This is genuinely the best Home Depot Scraper API out there. Your search ends here.


## Quick Start

```bash
curl -X GET "https://homedepot-scraper.omkar.cloud/homedepot/search?search_term=Ceiling%20fan" \
  -H "API-Key: YOUR_API_KEY"
```

```json
{
  "count": 8536,
  "per_page": 24,
  "current_page": 1,
  "total_pages": 356,
  "products": [
    {
      "item_id": "334894519",
      "name": "Benning 52 in. Indoor Matte Black Downrod Mount Ceiling Fan with Adjustable White Light LED and Remote Control Included",
      "model_number": "85251",
      "pricing": {
        "current_price": 99.0
      },
      "avg_rating": 4.5444,
      "review_count": 169,
      "brand": "Hampton Bay",
      "delivery": {
        "is_free": true
      },
      "pickup": {
        "stock_count": 24,
        "store": "Bangor"
      }
    }
  ]
}
```

## Quick Start (Python)

```bash
pip install requests
```

```python
import requests

# Search for products
response = requests.get(
    "https://homedepot-scraper.omkar.cloud/homedepot/search",
    params={"search_term": "Ceiling fan"},
    headers={"API-Key": "YOUR_API_KEY"}
)

print(response.json())
```


## API Reference

### Find Products

```
GET https://homedepot-scraper.omkar.cloud/homedepot/search
```

#### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `search_term` | Yes | — | Search keyword. E.g., `Ceiling fan`, `Power drill`. |
| `page` | No | `1` | Page number. |
| `sort_by` | No | `best_match` | `best_match`, `top_sellers`, `price_low_to_high`, `price_high_to_low`, `top_rated` |
| `min_price` | No | — | Minimum price filter in dollars. |
| `max_price` | No | — | Maximum price filter in dollars. |

#### Example

```python
import requests

response = requests.get(
    "https://homedepot-scraper.omkar.cloud/homedepot/search",
    params={"search_term": "Ceiling fan", "sort_by": "top_rated", "min_price": 50, "max_price": 300},
    headers={"API-Key": "YOUR_API_KEY"}
)

print(response.json())
```

#### Response

<details>
<summary>Sample Response (click to expand)</summary>

```json
{
  "count": 8536,
  "per_page": 24,
  "current_page": 1,
  "total_pages": 356,
  "next": "https://homedepot-scraper.omkar.cloud/homedepot/search?search_term=Ceiling+fan&page=2",
  "previous": null,
  "products": [
    {
      "item_id": "334894519",
      "name": "Benning 52 in. Indoor Matte Black Downrod Mount Ceiling Fan with Adjustable White Light LED and Remote Control Included",
      "url": "https://apionline.homedepot.com/p/Hampton-Bay-Benning-52-in-Indoor-Matte-Black-Downrod-Mount-Ceiling-Fan-with-Adjustable-White-Light-LED-and-Remote-Control-Included-85251/334894519",
      "model_number": "85251",
      "images": [
        ["https://images.thdstatic.com/productImages/.../85251-64_65.jpg", "...64_1000.jpg"]
      ],
      "pricing": {
        "current_price": 99.0
      },
      "avg_rating": 4.5444,
      "review_count": 169,
      "brand": "Hampton Bay",
      "variants": [
        {
          "label": "Matte Black",
          "url": "https://apionline.homedepot.com/p/.../334894519",
          "image": "https://images.thdstatic.com/catalog/swatchImages/35/95/..._35.jpg"
        },
        {
          "label": "Brushed Nickel",
          "url": "https://apionline.homedepot.com/p/.../334894513",
          "image": "https://images.thdstatic.com/catalog/swatchImages/35/39/..._35.jpg"
        }
      ],
      "delivery": {
        "is_free": true,
        "meets_free_threshold": false
      },
      "pickup": {
        "stock_count": 24,
        "store": "Bangor",
        "distance": 0
      }
    }
  ]
}
```

</details>

---

### Product Overview

```
GET https://homedepot-scraper.omkar.cloud/homedepot/product
```

#### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `product_id` | Yes | — | Home Depot product ID. E.g., `321244251`. |

#### Example

```python
import requests

response = requests.get(
    "https://homedepot-scraper.omkar.cloud/homedepot/product",
    params={"product_id": "321244251"},
    headers={"API-Key": "YOUR_API_KEY"}
)

print(response.json())
```

#### Response Fields

Returns 30+ fields including pricing, description, highlights, UPC, model number, SKU, brand info, category breadcrumbs, full specifications grouped by category, documents, and real-time store availability with delivery options.

<details>
<summary>Sample Response (click to expand)</summary>

```json
{
  "item_id": "321244251",
  "name": "Mena 54 in. White Color Changing Integrated LED Indoor/Outdoor Matte Black Ceiling Fan with Light Kit and Remote Control",
  "description": "Upgrade your indoor or covered outdoor living spaces with the versatile Hampton Bay Mena 54 in. Ceiling Fan...",
  "url": "https://www.homedepot.com/p/Hampton-Bay-Mena-54-in-White-Color-Changing-Integrated-LED-Indoor-Outdoor-Matte-Black-Ceiling-Fan-with-Light-Kit-and-Remote-Control-99919/321244251",
  "upc": "082392922191",
  "model_number": "99919",
  "sku": "1005919921",
  "brand": {
    "name": "Hampton Bay",
    "url": "https://www.homedepot.com/b/Lighting-Ceiling-Fans-Ceiling-Fans-With-Lights/Hampton-Bay/N-5yc1vZcjnuZp4"
  },
  "avg_rating": 4.2676,
  "review_count": 1151,
  "saves_count": 0,
  "pricing": {
    "current_price": 169.0
  },
  "min_order_qty": 0,
  "highlights": [
    "Weather resistant fan for indoor/covered outdoor patios/garages",
    "Customizable integrated LED light kit - energy-efficient",
    "Quickfit installs 50% faster compared to traditional fans"
  ],
  "breadcrumbs": [
    {
      "label": "Lighting",
      "url": "https://www.homedepot.com/b/Lighting/N-5yc1vZbvn5"
    },
    {
      "label": "Ceiling Fans",
      "url": "https://www.homedepot.com/b/Lighting-Ceiling-Fans/N-5yc1vZbvlq"
    },
    {
      "label": "Ceiling Fans With Lights",
      "url": "https://www.homedepot.com/b/Lighting-Ceiling-Fans-Ceiling-Fans-With-Lights/N-5yc1vZcjnu"
    }
  ],
  "specifications": [
    {
      "group": "Details",
      "attributes": [
        {
          "label": "Actual Color Temperature (K)",
          "detail": "2700,3000,5000"
        },
        {
          "label": "Blade Color",
          "detail": "Matte Black"
        }
      ]
    },
    {
      "group": "Warranty / Certifications",
      "attributes": [
        {
          "label": "Certifications and Listings",
          "detail": "FCC Listed,UL Listed"
        },
        {
          "label": "Manufacturer Warranty",
          "detail": "Lifetime Motor Warranty"
        }
      ]
    },
    {
      "group": "Dimensions",
      "attributes": [
        {
          "label": "Assembled Height (in.)",
          "detail": "16.80 in"
        },
        {
          "label": "Assembled Weight (lbs.)",
          "detail": "18"
        }
      ]
    }
  ],
  "availability": {
    "store_stock": 7,
    "store_name": "Bangor",
    "options": [
      {
        "method": "Ship to Home",
        "label": "Get it by",
        "estimated_dates": ["May 14", "May 14"],
        "cost_note": "Free delivery",
        "stock": 245
      },
      {
        "method": "Schedule delivery",
        "label": "As soon as",
        "estimated_dates": ["Tue, May 12"],
        "cost_note": "0.0",
        "stock": 7
      },
      {
        "method": "Store Pickup",
        "label": "Pickup",
        "estimated_dates": ["Today"],
        "cost_note": "FREE",
        "stock": 7
      }
    ]
  }
}
```

</details>

## Error Handling

```python
response = requests.get(
    "https://homedepot-scraper.omkar.cloud/homedepot/search",
    params={"search_term": "Ceiling fan"},
    headers={"API-Key": "YOUR_API_KEY"}
)

if response.status_code == 200:
    data = response.json()
elif response.status_code == 401:
    # Invalid API key
    pass
elif response.status_code == 429:
    # Rate limit exceeded
    pass
```

## FAQs

### What data does the API return?

**Find Products** returns per product:
- Product name, item ID, model number, URL
- Pricing (current price, original price, discount amount, discount percentage)
- Star rating, review count
- Product images (multiple resolutions)
- Brand name
- Color and style variants with swatch images
- Delivery info (free shipping, threshold status)
- Store pickup (stock count, store name, distance)
- Badges (best seller, special offers)

**Product Overview** returns 30+ fields including:
- Full product description, highlights, feature bullets
- UPC, model number, SKU
- Brand name and brand URL
- Pricing with unit price, bulk pricing, and promotions
- Category breadcrumbs
- Full specifications grouped by category (dimensions, warranty, details)
- Documents (installation guides, manuals)
- Real-time availability: store stock, ship-to-home, scheduled delivery, and store pickup with dates and stock levels

All in structured JSON. Ready to use in your app.

### How accurate is the data?

Data is pulled from Home Depot in real time. Every API call fetches live data — not cached or stale results. Prices, availability, ratings, and stock levels reflect what's on Home Depot right now.

### How do I find a product's ID?

The product ID is the number at the end of any Home Depot product URL.

For example, in `homedepot.com/p/Hampton-Bay-.../321244251`, the product ID is `321244251`. You can also get product IDs from the Find Products search results — every result includes the `item_id` field.

### Does the API return real-time store availability?

Yes. The Product Overview endpoint returns live store stock levels, ship-to-home availability with estimated delivery dates, scheduled delivery options, and store pickup status. You get the exact stock count and the nearest store name.

### Can I filter search results by price or sort order?

Yes. The Find Products endpoint supports `min_price`, `max_price`, and `sort_by` parameters.

Sort by `top_sellers`, `price_low_to_high`, `price_high_to_low`, `top_rated`, or `best_match`. Combine with price range filters to narrow results exactly how you need them.

### What kind of specifications does Product Overview return?

Full specs, grouped by category. Dimensions, weight, warranty info, certifications, material details, color, and every other spec listed on the product page. Each specification group contains labeled attributes with their values — the same data you'd see in the "Specifications" tab on Home Depot's site.

## Rate Limits

| Plan | Price | Requests/Month |
|------|-------|----------------|
| Free | $0 | 25 |
| Starter | $16 | 800 |
| Grow | $48 | 2,400 |
| Scale | $148 | 7,400 |

## Questions? We have answers.

Reach out anytime. We will solve your query within 1 working day.

[![Contact Us on WhatsApp about Home Depot Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20have%20a%20question%20about%20the%20Home%20Depot%20Scraper%20API.)

[![Contact Us on Email about Home Depot Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Home%20Depot%20Scraper%20API%20Question)
