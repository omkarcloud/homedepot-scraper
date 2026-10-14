FROM chetan1111/botasaurus:chrome-151

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN python -m pip install --no-cache-dir -r requirements.txt

RUN mkdir app
WORKDIR /app
COPY . /app

EXPOSE 8000

# Google Chrome ships in the base image. It runs headed on a virtual display:
# every request is a fetch inside a Chrome page parked on homedepot.com.
CMD ["python", "run.py"]
