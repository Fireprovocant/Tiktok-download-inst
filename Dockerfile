FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000

# timeout alto porque baixar + converter vídeo pode demorar
CMD ["sh", "-c", "gunicorn -w 2 --threads 4 -b 0.0.0.0:${PORT} --timeout 300 app:app"]
