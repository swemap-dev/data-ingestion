
from backend.celery import app
i = app.control.inspect()
registered = i.registered()
print("Registered Tasks:")
if registered:
    for worker, tasks in registered.items():
        print(f"Worker: {worker}")
        for t in tasks:
            print(f" - {t}")
        if 'git_blame_ingestion_app.tasks.finalize_repo_ingestion' not in tasks:
            print(f"\nWARNING: finalize_repo_ingestion is NOT registered on {worker}. The worker needs to be restarted.")
else:
    print("No workers found or no response.")
