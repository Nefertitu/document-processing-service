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
RUN curl -sSL https://install.python-poetry.org | python3 - --version $POETRY_VERSION

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main --no-root

COPY . .

RUN adduser --disabled-password --gecos '' appuser

RUN mkdir -p /app/static /app/staticfiles /app/media /var/celerybeat-schedule && \
    chown -R appuser:appuser /app/static /app/staticfiles /app/media /var/celerybeat-schedule && \
    chmod -R 775 /app/static /app/staticfiles /app/media /var/celerybeat-schedule
#
# RUN mkdir -p /app/media/documents /app/media/temp_uploads /app/media/temp_answers && \
#     chown -R appuser:appuser /app/media && \
#     chmod -R 775 /app/media

RUN rm -rf ~/.cache/pip

USER appuser

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
