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
# The -B flag runs the Beat scheduler alongside the worker so you only need one terminal!
celery -A backend worker -B -l info
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

## Render
I've just written the GitHub Action file for you at .github/workflows/wake_server.yml!

Because GitHub Actions run on UTC time, and New York Time has Daylight Saving Time (switching between UTC-4 and UTC-5), scheduling crons is notoriously annoying. I've designed this workflow to ping your server at a few intervals right before 3 AM and 4 AM UTC. This completely sidesteps Daylight Saving Time and guarantees your server will be wide awake exactly at Midnight, all year round!

Here is the step-by-step guide to get it fully wired up:

**1. Add your Render URL to GitHub Secrets**

Because your Render URL might change or you might want to keep it private, the script expects a GitHub Secret named RENDER_WEB_URL.
1. Once your Render Web Service is deployed, copy its live URL (e.g., https://swemap-web.onrender.com). Make sure there is no trailing slash!
2. Go to your repository on GitHub.com.
3. Click Settings > Secrets and variables > Actions.
4. Click New repository secret.
5. Name: RENDER_WEB_URL
6. Value: Paste your Render URL.
7. Click Add secret.

**2. Commit and Push**
Now, simply commit the file I just created:

```bash
git add .github/workflows/wake_server.yml
git commit -m "Add GitHub action to wake Render server before midnight"
git push origin main
```

**3. Verify it works!**
You don't have to wait until midnight to test it.
1. Go to the Actions tab on your GitHub repository.
2. You will see a workflow on the left called Wake Render Server. Click it.
3. Because I added the workflow_dispatch trigger, you will see a "Run workflow" button on the right side of the screen.
4. Click it to manually trigger the ping! If the run succeeds (green checkmark), your workaround is completely finished and fully operational!

## Supabase
### Clear DB
```sql
-- Clear all repositories from DB (but keep schema)
TRUNCATE TABLE repos RESTART IDENTITY CASCADE;
```