FROM nginx:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
    adduser \
    && rm -rf /var/lib/apt/lists/*

RUN adduser --disabled-password --gecos '' appuser

RUN mkdir -p /app/staticfiles && \
    chown -R appuser:appuser /app/staticfiles && \
    chmod -R 755 /app/staticfiles

RUN mkdir -p /app/media

COPY nginx.conf /etc/nginx/nginx.conf
COPY conf.d/default.conf /etc/nginx/conf.d/default.conf

EXPOSE 80