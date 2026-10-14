FROM chetan1111/botasaurus:chrome-151

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN python -m pip install --no-cache-dir -r requirements.txt

RUN mkdir app
WORKDIR /app
COPY . /app

EXPOSE 8000

# Google Chrome ships in the base image: it opens once (headed, on a virtual
# display) to pass Home Depot's Akamai check; every request after that is
# plain HTTP.
CMD ["python", "run.py"]
