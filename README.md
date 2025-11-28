# Data Ingestion Engine

A data ingestion engine for pulling repository metadata and file contents from various data sources, starting with GitHub.

## Setup

1. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   ```

2. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file with your GitHub token:
   ```bash
   echo "GITHUB_TOKEN=your_github_token_here" > .env
   ```
   
   Or manually create `.env` with:
   ```
   GITHUB_TOKEN=your_github_token_here
   ```

## Usage

### GitHub Repository Metadata

```python
from src.github import GitHubClient

client = GitHubClient()
repo = client.get_repository('owner', 'repo-name')
```

### GitHub File Contents

```python
from src.github import GitHubClient, FileContentsService

client = GitHubClient()
service = FileContentsService(client)
contents = service.get_recursive_file_contents('owner', 'repo-name')
```

## GitHub App Webhook Server

The GitHub App webhook server receives events from GitHub and processes repository updates. This is separate from the initial data ingestion code and is used for keeping repository metadata up to date.

### Setup

1. **Create a GitHub App:**
   - Go to https://github.com/settings/apps/new
   - Set a name and homepage URL
   - Set webhook URL to your SMEE channel URL (e.g., `https://smee.io/YAYdUfIjUdH58Xgx`)
   - Set webhook secret (generate a random string)
   - Select repository permissions (at minimum: `Read access to metadata`)
   - Subscribe to events: `push`, `repository`, `create`, `delete`
   - Create the app

2. **Install the App:**
   - Go to your app's settings
   - Click "Install App"
   - Select the organization where you want to install it
   - Choose which repositories to grant access to

3. **Get App Credentials:**
   - App ID: Found in the "About" section of your app
   - Private Key: Go to "Private keys" section, generate a new key, and download it
   - Webhook Secret: The secret you set when creating the app

4. **Configure Environment Variables:**
   Add to your `.env` file:
   ```
   GITHUB_APP_ID=your_app_id_here
   GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
   GITHUB_WEBHOOK_SECRET=your_webhook_secret_here
   ```
   
   **Important:** The private key must include `\n` for newlines. You can format it in one of two ways:
   
   **Option A - Inline with escaped newlines (recommended for .env files):**
   ```
   GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
   ```
   
   **Option B - File path (if the key is in a separate file):**
   ```
   GITHUB_APP_PRIVATE_KEY=/path/to/your/private-key.pem
   ```
   
   Make sure the key includes the `-----BEGIN` and `-----END` markers with proper newlines.

5. **Run the Webhook Server:**
   
   You'll need two terminal windows:
   
   **Terminal 1 - Start the webhook server:**
   ```bash
   python -m src.github.app.server
   ```
   
   Or using uvicorn directly:
   ```bash
   uvicorn src.github.app.server:app --host 0.0.0.0 --port 8000
   ```
   
   **Terminal 2 - Start the SMEE client to forward events:**
   ```bash
   pysmee forward https://smee.io/YAYdUfIjUdH58Xgx http://localhost:8000/webhook
   ```
   
   The SMEE client will forward webhook events from your SMEE channel to your local server.

### Webhook Events

The server handles the following GitHub events (more coming):
- **push**: When code is pushed to a repository

All events are logged with repository metadata. Database update logic is marked with TODO comments for future implementation.

### Local Development with SMEE

For local development, we use [SMEE](https://smee.io/) to forward webhook events from GitHub to your local server:

1. **Get your SMEE channel URL** (e.g., `https://smee.io/YAYdUfIjUdH58Xgx`)
2. **Configure your GitHub App** to send webhooks to your SMEE channel URL
3. **Run both services:**

   **Option A - Using the helper script (recommended):**
   ```bash
   ./scripts/run_webhook_dev.sh
   ```
   
   This will start both the SMEE client and webhook server together.
   
   **Option B - Manual (two terminals):**
   
   Terminal 1 - SMEE client (using official Node.js client via npx):
   ```bash
   npx --yes smee-client -u https://smee.io/YAYdUfIjUdH58Xgx -t http://localhost:8000/webhook
   ```
   
   Terminal 2 - Webhook server:
   ```bash
   python -m src.github.app.server
   ```

The SMEE client will automatically forward all webhook events from GitHub to your local server, allowing you to test without deploying to a public URL.

