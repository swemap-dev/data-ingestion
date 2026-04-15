# Setting up the Django Webhook Environment

## 0. Prerequisites
Ensure you are in the `django/backend` directory and have your environment active.

1. **Create .env File**
2.  **Start Redis** (Required for Celery):
    ```bash
    cd git_blame_ingestion_app
    docker compose up -d
    ```
3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
4.  **Run Migrations**:
    ```bash
    python manage.py makemigrations
    python manage.py migrate
    ```
5. **Create .env Files**:
    The file should include the following fields:
    ```
    DB_NAME='YOUR_POSTGRES_DB_NAME'
    DB_USER='YOUR_POSTGRES_USER_NAME'
    DB_PASSWORD='YOUR_POSTGRES_PASSWORD'
    CELERY_BROKER_URL='redis://localhost:6379/0'
    CELERY_RESULT_BACKEND='redis://localhost:6379/0'
    GITHUB_TOKEN="YOUR_GITHUB_TOKEN"
    ```

## 1. Start Up Sequence (Run in separate terminals)

### Terminal A: Celery Worker
Start Redis in the background:
```
brew install redis && brew services start redis
```

This processes the background jobs (Make sure Docker is up and running).
```bash
# Must be run from django/backend/ directory
celery -A backend worker -l info
```

### Terminal B: Django Server
This accepts the webhook requests.
```bash
python manage.py runserver
```

### Terminal C: Ngrok
This exposes your local server to GitHub.
```bash
ngrok http 8000
```

## 2. Update GitHub Webhook
1. Copy the forwarding URL from ngrok (e.g., `https://a1b2-c3d4.ngrok-free.app`).
2. Go to your GitHub Repository Settings -> Webhooks.
3. Edit your webhook.
4. **Payload URL**: `[YOUR_NGROK_URL]/api/webhook`
5. **Content type**: `application/json`
6. **Events**: "Push" events.
7. Save.

## 3. Verify
Trigger a push to your repo.
1. **Ngrok**: Shows `POST /api/webhook 200 OK`.
2. **Django**: Logs `Enqueuing job for...`.
3. **Celery**: Logs `Processing blame for...`.


# Dev

## Clear the Database
```bash
python manage.py flush
```

## Clear the Celery Queue
```bash
celery -A backend purge
```

## Run Management Command
Navigate to `django/backend/` directory.

Clears all application data:
```bash
python manage.py clear_app_data
```
Run initialization pass for all demo repo:
```bash
python manage.py init_repo "https://github.com/justin-chung-swemap/swemap-demo"
```

## Run LLM API
In a seperate terminal:
```
curl -X POST http://localhost:8000/api/risk/repos/24/generate-action-items?top_k=5
```

## Run Tests
Grant permission to postgres user to create database:
```bash
psql -U postgres -c "ALTER USER <YOUR_DB_USER> CREATEDB;"
```
In `django/backend` directory, run the tests of an app:
```bash
python manage.py test <app_name>

# Example: 
python manage.py test git_blame_ingestion_app
```
Run a class of tests of an app:
```bash
python manage.py test risk_dashboard.tests.ChangeFrequencyBasicTests -v2
```

## Supabase
### Dashboard (Local)
In ```data-ingestion/supabase/``` run ```supabase start```.
Data are stored in local docker container images. To view them, go to http://127.0.0.1:54323.

### Credentials
╭──────────────────────────────────────╮
│ 🔧 Development Tools                 │
├─────────┬────────────────────────────┤
│ Studio  │ http://127.0.0.1:54323     │
│ Mailpit │ http://127.0.0.1:54324     │
│ MCP     │ http://127.0.0.1:54321/mcp │
╰─────────┴────────────────────────────╯

╭──────────────────────────────────────────────────────╮
│ 🌐 APIs                                              │
├────────────────┬─────────────────────────────────────┤
│ Project URL    │ http://127.0.0.1:54321              │
│ REST           │ http://127.0.0.1:54321/rest/v1      │
│ GraphQL        │ http://127.0.0.1:54321/graphql/v1   │
│ Edge Functions │ http://127.0.0.1:54321/functions/v1 │
╰────────────────┴─────────────────────────────────────╯

╭───────────────────────────────────────────────────────────────╮
│ ⛁ Database                                                    │
├─────┬─────────────────────────────────────────────────────────┤
│ URL │ postgresql://postgres:postgres@127.0.0.1:54322/postgres │
╰─────┴─────────────────────────────────────────────────────────╯

╭──────────────────────────────────────────────────────────────╮
│ 🔑 Authentication Keys                                       │
├─────────────┬────────────────────────────────────────────────┤
│ Publishable │ sb_publishable_ACJWlzQHlZjBrEguHvfOxg_3BJgxAaH │
│ Secret      │ sb_secret_N7UND0UgjKTVK-Uodkm0Hg_xSvEMPvz      │
╰─────────────┴────────────────────────────────────────────────╯

╭───────────────────────────────────────────────────────────────────────────────╮
│ 📦 Storage (S3)                                                               │
├────────────┬──────────────────────────────────────────────────────────────────┤
│ URL        │ http://127.0.0.1:54321/storage/v1/s3                             │
│ Access Key │ 625729a08b95bf1b7ff351a663f3a23c                                 │
│ Secret Key │ 850181e4652dd023b7a98c58ae0d2d34bd487ee0cc3254aed6eda37307425907 │
│ Region     │ local                                                            │
╰────────────┴──────────────────────────────────────────────────────────────────╯