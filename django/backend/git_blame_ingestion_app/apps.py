import os
import sys

from django.apps import AppConfig


class GitBlameIngestionAppConfig(AppConfig):
    name = 'git_blame_ingestion_app'

    def ready(self):
        # Check if we are running 'runserver' command
        if 'runserver' in sys.argv:
            # Check if this is the main process (not the reloader)
            if os.environ.get('RUN_MAIN') == 'true':
                from .tasks import initialize
                # Hardcoded repo URL for now as per dev context
                repo_url = "https://github.com/justin-chung-swemap/Webhook_Test" # TODO: parameterize this
                print(f"Auto-initializing repository: {repo_url}")
                # initialize.delay(repo_url)
