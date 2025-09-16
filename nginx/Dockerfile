FROM nginx:latest

RUN adduser --disabled-password --gecos '' appuser

RUN mkdir -p /app/staticfiles && \
    chown -R appuser:appuser /app/staticfiles && \
    chmod -R 755 /app/staticfiles

RUN mkdir -p /app/media

RUN rm -f /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 80