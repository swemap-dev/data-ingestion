from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('git_blame_ingestion_app', '0018_repo_last_synced_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='module',
            name='designer_name',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
