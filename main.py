"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json.
"""
import json
import os

from homedepot import products, stores

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # an item id (internet number) or any homedepot.com product link
    save("product_204279858.json", products.details("204279858"))

    # 24 products per page, priced for the default store (#121, Atlanta GA)
    save("search_dewalt_drill.json", products.search("dewalt drill"))

    # stores near a city, with hours, phones and services
    save("stores_beverly_hills.json", stores.search({"query": "Beverly Hills, CA"}))
