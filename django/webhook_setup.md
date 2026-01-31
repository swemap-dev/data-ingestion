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

## 1. Startup Sequence (Run in separate terminals)

### Terminal A: Celery Worker
This processes the background jobs.
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
