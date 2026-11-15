FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/data /app/staticfiles \
    && chown -R app:app /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

USER app
EXPOSE 8000

CMD ["gunicorn", "fintrac.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
