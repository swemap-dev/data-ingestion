import os
import django
from django.db import connection

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

with connection.cursor() as cursor:
    cursor.execute("DROP TABLE IF EXISTS module_role_assignments CASCADE;")
    print("Dropped table module_role_assignments")
