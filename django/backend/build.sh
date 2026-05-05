#!/usr/bin/env bash
# exit on error
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

# Collect static files for Django Admin
python manage.py collectstatic --no-input

# Apply database migrations
python manage.py migrate
