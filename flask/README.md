# Data Ingestion Engine (Dev Branch)

A data ingestion engine for pulling repository metadata and file contents from various data sources, starting with GitHub.

## Setup
1. Create and activate a virtual environment

   venv:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
   anaconda:
   ```bash
   conda create -n data-ingestion python=3.14
   conda activate data-ingestion
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
The software is split into two main steps:
1. Configure Postgres Database: Follow the instructions in `db_schema/README.md`
2. Run Ingestion Engine webhook: Follow the instructions in `oracle/blame/README.md`

