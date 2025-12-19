# Git Blame Webhook & Polling

This module implements a real-time system to detect new Git commits and update the blame database.

## Components
- **`webhook.py`**: Flask server listening on `/webhook` for GitHub push events.
- **`polling.py`**: Fallback script to poll GitHub for changes in monitored repositories.
- **`pipeline.py`**: Shared logic to fetch blame data via GraphQL and update the DB using `range_cutter.py`.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Ensure `.env` is configured with `GITHUB_TOKEN`.
3. Ensure PostgreSQL database is running and reachable via the DSN in `db_schema/oracle/range_cutter.py`.

## Usage

### 1. Webhook Server (Real-time)

Start the webhook server:
```bash
python oracle/blame/webhook.py
```
This runs on port **5001** by default.

#### Expose to Internet
To receive GitHub webhooks, use **ngrok**:
```bash
ngrok http 5001
```
Copy the HTTPS URL (e.g., `https://abc.ngrok-free.app`).

#### Configure GitHub
1. Go to Repo Settings > Webhooks > Add webhook.
2. **Payload URL**: `[NGROK Forwarding URL]/webhook`.
3. **Content type**: `application/json`.
4. **Events**: "Just the push event".

### 2. Polling Script (Fallback)

If you cannot use webhooks, use the polling script:
```bash
python oracle/blame/polling.py
```
This will check for changes every 5 minutes and process new commits.
State is stored in `polling_state.json`.
