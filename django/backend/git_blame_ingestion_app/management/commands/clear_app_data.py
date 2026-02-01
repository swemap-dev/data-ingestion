from django.core.management.base import BaseCommand
from django.db import transaction
from git_blame_ingestion_app.models import (
    Repo, Module, File, Engineer, LineOwnership, 
    FileOwnershipMetric, ModuleContribution, FileContribution,
    ModuleSkill, EngineerSkill, FileDependency, Review
)

class Command(BaseCommand):
    help = 'Clears all application data (Repos, Files, etc.) but preserves Users/Admin'

    def handle(self, *args, **options):
        self.stdout.write("Clearing application data...")
        
        with transaction.atomic():
            # Delete in order of dependency to avoid protected foreign key issues
            # though standard cascade delete should handle most.
            
            # Metrics and Ownership
            LineOwnership.objects.all().delete()
            FileOwnershipMetric.objects.all().delete()
            ModuleContribution.objects.all().delete()
            FileContribution.objects.all().delete()
            ModuleSkill.objects.all().delete()
            EngineerSkill.objects.all().delete()
            FileDependency.objects.all().delete()
            Review.objects.all().delete()
            
            # Core Structure
            File.objects.all().delete()
            Module.objects.all().delete()
            Repo.objects.all().delete()
            
            # Engineers (if you want to keep them, comment this out)
            Engineer.objects.all().delete()
            
        self.stdout.write(self.style.SUCCESS("Successfully cleared application data. Admin user preserved."))
