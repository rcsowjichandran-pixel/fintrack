# FinTrack

## Run locally on Windows

Activate the virtual environment, generate and set a Django secret key and optionally set a Gemini API key, then start Django:

```powershell
venv\Scripts\activate
$env:DJANGO_SECRET_KEY = (python -c "import secrets; print(secrets.token_urlsafe(50))")
$env:DJANGO_SECURE_SSL_REDIRECT = "False"
$env:DJANGO_SECURE_HSTS_SECONDS = "0"
$env:DJANGO_SESSION_COOKIE_SECURE = "False"
$env:DJANGO_CSRF_COOKIE_SECURE = "False"
$env:GEMINI_API_KEY = "your-Gemini-API-key"
python manage.py runserver
```

`GEMINI_API_KEY` is optional for the rest of the app. The Financial Insights page explains when predictions are unavailable. `GEMINI_MODEL` can override the default `gemini-3.8-flash` model.

## Tests

```powershell
venv\Scripts\activate
$env:DJANGO_SECRET_KEY = "test-only-secret-value"
python manage.py test accounting
python manage.py test
```

## Container hosting

Install Docker with Docker Compose, set `DJANGO_SECRET_KEY` in the shell, and run:

```powershell
$env:DJANGO_SECRET_KEY = (python -c "import secrets; print(secrets.token_urlsafe(50))")
$env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1"
$env:GEMINI_API_KEY = "your-Gemini-API-key"
docker compose up --build
```

The container runs migrations and collects static files before starting Gunicorn. SQLite data is kept in the `fintrack_data` volume at `/app/data/db.sqlite3`. The container listens on `PORT` (8000 in Compose; hosting platforms can supply their own port).

For a Render deployment using SQLite, create a Docker Web Service from this GitHub repository and attach a persistent disk mounted at `/app/data`. Render services have an ephemeral filesystem by default, and persistent disks require a paid web service. Set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` to the service hostname, `DJANGO_CSRF_TRUSTED_ORIGINS` to its HTTPS origin, and optionally `GEMINI_API_KEY`. For a TLS host, set `DJANGO_SECURE_SSL_REDIRECT=True`, `DJANGO_SESSION_COOKIE_SECURE=True`, `DJANGO_CSRF_COOKIE_SECURE=True`, and `DJANGO_SECURE_HSTS_SECONDS` to an appropriate value. Configure the SMTP environment variables if the app needs to send email.
