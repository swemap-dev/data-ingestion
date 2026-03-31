# SWEMAP Data Ingestion Monorepo

This repository contains the various services responsible for ingesting and processing data for SWEMAP.

## Structure

*   **`flask/`**: Separate microservice for GitHub Webhook handling and Blame processing (Legacy/Proof of Concept).
*   **`cooccurrence/`**: C++ implementation for file co-occurrence analysis.
*   **`django/`** (Developing MVP): The future enterprise backend logic.

## Developing

Each subdirectory is an independent project. Please refer to the `README.md` inside each directory for specific setup instructions.