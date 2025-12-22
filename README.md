# Data Ingestion Engine (Dev Branch)

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

## Run Software
1. Set up Database: refer to `db_schema/README.md`
2. Run Ingestion Engine webhook: refer to `oracle/blame/README.md`

