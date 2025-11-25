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

