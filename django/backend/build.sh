#!/usr/bin/env bash
# exit on error
set -o errexit

# Render runs this from the repo root, so we must CD into the backend folder first
cd django/backend

pip install --upgrade pip
pip install -r requirements.txt

# Collect static files for Django Admin
python manage.py collectstatic --no-input

# Apply database migrations
python manage.py migrate
