import os
import sys
from django.conf import settings
from psycopg.types.range import Range as NumericRange

# Setup Django environment manually
if not settings.configured:
    settings.configure(
        DEBUG=True, 
        SECRET_KEY='test-key', 
        TIME_ZONE='UTC',
        INSTALLED_APPS=[
            'django.contrib.contenttypes',
            'git_blame_ingestion_app', 
        ],
        # We need a db connection for this test as it uses ORM expressions
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3', # Use sqlite for quick test if possible? 
                # Wait, IntegerRangeField is Postgres specific. 
                # SQLite doesn't support it natively in the same way Django maps it usually.
                # However, since we are just checking if the query *compiles* without FieldError, 
                # maybe we don't need to execute it fully if we can mock?
                # Actually, the error `Cannot infer type of '-'` happens at Query Construction time, 
                # likely before execution on DB? 
                # "django.core.exceptions.FieldError" suggests it happens during query construction/resolution.
                # So we might not need a real Postgres DB to see if the error is gone?
                # But let's try to just load the code and inspect the query.
            }
        }
    )
    # We might need to mock or just rely on the fact that we can import it.
    
    # Actually, to properly test this we need a real connection because 'Upper'/'Lower' might be backend specific?
    # No, the error is a Django validation error during query construction.
    
import django
django.setup()

try:
    from git_blame_ingestion_app.services.ingestion import recalculate_metrics
    from git_blame_ingestion_app.models import File, LineOwnership, Engineer
    from django.db.models import F, Sum, IntegerField, ExpressionWrapper
    from git_blame_ingestion_app.services.ingestion import Upper, Lower
    
    print("Successfully imported ingestion module.")
    
    # Let's try to construct the query manually to see if it raises FieldError
    # We don't need to run it against DB if the error is essentially a type inference error.
    
    # Mocking queryset construction
    qs = LineOwnership.objects.none()
    
    # The problematic part:
    try:
        qs.annotate(
            lines_owned=Sum(
                ExpressionWrapper(
                    Upper(F('line_range')) - Lower(F('line_range')),
                    output_field=IntegerField()
                )
            )
        ) # Just constructing this should trigger the validation if it was failing before?
        
        # Actually, let's look at the original error trace.
        # It happens at:
        # File ".../django/db/models/sql/compiler.py", line 75, in setup_query
        # ...
        # File ".../django/db/models/expressions.py", line 752, in _resolve_output_field
        # raise FieldError(...)
        
        # So yes, simply constructing the queryset (or accessing its query, or trying to compile it) 
        # should trigger it.
        
        # Taking it a step further to trigger compilation:
        query = qs.annotate(
             lines_owned=Sum(
                ExpressionWrapper(
                    Upper(F('line_range')) - Lower(F('line_range')),
                    output_field=IntegerField()
                )
            )
        ).query
        print("Query constructed successfully!")
        
    except Exception as e:
        print(f"FAILED: {e}")
        # raise e

except Exception as e:
    print(f"Import/Setup Error: {e}")
