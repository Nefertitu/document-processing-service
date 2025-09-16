FROM nginx:latest

RUN adduser --disabled-password --gecos '' appuser

RUN mkdir -p /app/staticfiles && \
    chown -R appuser:appuser /app/staticfiles && \
    chmod -R 755 /app/staticfiles

RUN mkdir -p /app/media

COPY nginx.conf /etc/nginx/nginx.conf

RUN echo "client_max_body_size 50M;" > /etc/nginx/conf.d/client_size.conf

RUN chmod 644 /etc/nginx/conf.d/client_size.conf

EXPOSE 80