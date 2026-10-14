# 🛠️ Homedepot Scraper

Homedepot Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Home Depot data for free.

## ✨ What Can I Get?

- 📦 **Full details on 1M+ products** — price, promos, specs, images, videos & UPC
- 🔍 **Search & browse every department** — sort and filter by brand, price, rating & pickup
- 🏬 **Live stock at the store near you** — quantity, aisle & bay, pickup & delivery
- ⭐ **Reviews, Q&A & daily deals** — star histograms, brand answers, Special Buys

## 🧰 Example: A Full Home Depot Product

```json
{
  "id": "204279858",
  "name": "20V MAX Cordless 1/2 in. Drill/Driver, (2) 20V 1.3Ah Batteries, Charger and Bag",
  "link": "https://www.homedepot.com/p/DEWALT-20V-MAX-Cordless-1-2-in-Drill-Driver-2-20V-1-3Ah-Batteries-Charger-and-Bag-DCD771C2/204279858",
  "brand": "DEWALT",
  "model_number": "DCD771C2",
  "upc": "885911325905",
  "image": "https://images.thdstatic.com/productImages/d00a1384-69ea-4f77-a5c3-c0ac8fd531fa/svn/dewalt-power-drills-dcd771c2-64_1000.jpg",
  "rating": { "average": 4.62, "count": 11404 },
  "pricing": { "currency": "USD", "price": 119.0, "is_special_buy": false, "is_clearance": false },
  "badges": ["Top Rated"],
  "highlights": ["Includes Drill Driver & Tool Bag", "(2) 20-Volt Batteries 1.3Ah & Charger"],
  "fulfillment": {
    "pickup": { "is_available": false, "quantity": 0, "is_ship_to_store_available": true },
    "delivery": { "is_available": true, "online_quantity": 534 }
  },
  "specifications": [
    { "group": "Details", "specs": [{ "name": "Battery Voltage (V)", "value": "20V" }, { "name": "Maximum Speed (RPM)", "value": "1500 RPM" }] }
  ],
  "key_features": [{ "name": "Chuck Size (In.)", "value": "1/2 In." }],
  "categories": ["Tools", "Power Tools", "Drills", "Power Drills"],
  "store": { "id": "121", "name": "Cumberland", "city": "Atlanta", "state": "GA" },
  "return_policy": "90-Day"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Home Depot Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/homedepot-scraper
cd homedepot-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

The first request opens Google Chrome once, for a few seconds, to pass Home Depot's bot check. Every request after that is plain HTTP. You need Google Chrome installed, or use `docker compose up`.

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/details?product=204279858"
```

```json
{
  "product": {
    "id": "204279858",
    "name": "20V MAX Cordless 1/2 in. Drill/Driver, (2) 20V 1.3Ah Batteries, Charger and Bag",
    "link": "https://www.homedepot.com/p/DEWALT-20V-MAX-Cordless-1-2-in-Drill-Driver-2-20V-1-3Ah-Batteries-Charger-and-Bag-DCD771C2/204279858",
    "brand": "DEWALT",
    "model_number": "DCD771C2",
    "rating": { "average": 4.62, "count": 11404 },
    "pricing": { "currency": "USD", "price": 119.0 },
    "fulfillment": {
      "pickup": { "is_available": false, "quantity": 0, "is_ship_to_store_available": true },
      "delivery": { "is_available": true, "online_quantity": 534 }
    },
    "categories": ["Tools", "Power Tools", "Drills", "Power Drills"],
    "quantity_limit": 5,
    "return_policy": "90-Day",
    "store": { "id": "121", "name": "Cumberland", "city": "Atlanta", "state": "GA", "zip": "30339" }
  }
}
```

All 12 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

12 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Product Details | `/products/details` | Everything about one product in a single call |
| Search Products | `/products/search` | 24 products per page; sort and filter by brand, price, rating |
| Lookup Product | `/products/lookup` | Exact product from a model number, UPC or store SKU |
| Bulk Products | `/products/bulk` | Up to 25 products with price and stock in one call |
| Product Availability | `/products/availability` | Stock, aisle and bay at the stores near you |
| Product Reviews | `/products/reviews` | Reviews with star histogram, photos and brand replies |
| Product Questions | `/products/questions` | Customer questions with every answer, brand answers included |
| Departments | `/categories` | All top-level departments with their category codes |
| Category Products | `/categories/products` | Any category or brand page, with filters and subcategories |
| Search Stores / Store Details | `/stores/search`, `/stores/details` | Address, hours, phones and services for every store |
| Daily Deals | `/deals` | Today's Special Buy deals, priced for your store |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-homedepot-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-homedepot-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-homedepot-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/details",
    params={"product": "204279858"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Homedepot Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Homedepot%20Scraper%20API.)

[![Ask Us by Email about Homedepot Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Homedepot%20Scraper%20API&body=I%20need%20help%20using%20the%20Homedepot%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/homedepot-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/homedepot-scraper)
