from django.core.management.base import BaseCommand
from git_blame_ingestion_app.tasks import initialize

class Command(BaseCommand):
    help = 'Manually initializes a repository by queuing the processing task.'

    def add_arguments(self, parser):
        parser.add_argument('repo_url', type=str, default="https://github.com/justin-chung-swemap/swemap-demo", help='The full URL of the GitHub repository')

    def handle(self, *args, **options):
        repo_url = options['repo_url']
        self.stdout.write(f"Triggering initialization for: {repo_url}")
        
        # Trigger the Celery task
        # Note: If Celery worker is not running, this will just sit in Redis.
        # To run synchronously (for debugging), you would import the logic directly,
        # but tasks are best run via .delay() in this architecture.
        initialize.delay(repo_url)
        
        self.stdout.write(self.style.SUCCESS(f"Initialization task queued for {repo_url}"))
