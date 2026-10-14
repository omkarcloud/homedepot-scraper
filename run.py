"""Start the Home Depot Scraper API.

    python run.py            # http://localhost:8000
    PORT=9000 python run.py  # another port

Then:  curl "http://localhost:8000/products/details?product=204279858"

The first request opens Google Chrome once (a few seconds) to pass Home
Depot's Akamai bot check; every request after that is plain HTTP.
"""
import bottle
from cheroot import wsgi

import config
import routes  # noqa: F401  (mounts the routes on bottle's default app)


def main():
    app = bottle.default_app()
    print(f"Home Depot Scraper listening on http://localhost:{config.PORT}/")
    print(f"Try:  curl \"http://localhost:{config.PORT}/products/details?product=204279858\"")
    server = wsgi.Server(("0.0.0.0", config.PORT), app, server_name="homedepot-scraper", numthreads=16)
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
