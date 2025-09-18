FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    libpq-dev \
    python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV POETRY_HOME=/opt/poetry
ENV POETRY_VERSION=2.2.0
ENV PATH="$POETRY_HOME/bin:$PATH"
ENV DJANGO_SETTINGS_MODULE=config.settings
RUN curl -sSL https://install.python-poetry.org | python3 - --version $POETRY_VERSION

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main --no-root

COPY . .

RUN mkdir -p /app/media/documents /app/media/temp_uploads /app/media/temp_answers
RUN mkdir -p /app/static /app/staticfiles
RUN chmod -R 755 /app/media /app/static /app/staticfiles

RUN adduser --disabled-password --gecos '' appuser
RUN chown -R appuser:appuser /app

COPY docker-entrypoint.sh /
RUN chmod +x /docker-entrypoint.sh

RUN rm -rf ~/.cache/pip

USER appuser

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
