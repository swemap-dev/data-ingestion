from django.db import models
from django.contrib.postgres.fields import IntegerRangeField
from django.utils.translation import gettext_lazy as _

# 1. Enums
class SkillType(models.TextChoices):
    LANGUAGE = 'LANGUAGE', _('Language')
    FRAMEWORK = 'FRAMEWORK', _('Framework')
    TOOL = 'TOOL', _('Tool')
    PLATFORM = 'PLATFORM', _('Platform')

class CommitType(models.TextChoices):
    COMMIT = 'COMMIT', _('Commit')
    PR = 'PR', _('Pull Request')

class InteractionType(models.TextChoices):
    DESIGNED = 'DESIGNED', _('Designed')
    WROTE = 'WROTE', _('Wrote')
    REVIEWED = 'REVIEWED', _('Reviewed')

class DependencyType(models.TextChoices):
    INTERNAL = 'INTERNAL', _('Internal')
    EXTERNAL = 'EXTERNAL', _('External')

# 2. Independent Models

class Engineer(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True, max_length=255)
    team = models.CharField(max_length=100, null=True, blank=True)
    join_date = models.DateTimeField(auto_now_add=True)
    last_active = models.DateTimeField(null=True, blank=True)
    recs = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'engineers'
        managed = True

    def __str__(self):
        return self.name

class Repo(models.Model):
    name = models.CharField(max_length=255)
    owner = models.CharField(max_length=255, default='unknown')
    url = models.CharField(max_length=255, null=True, blank=True)
    language = models.CharField(max_length=100, null=True, blank=True)
    risk_score = models.FloatField(null=True, blank=True)
    rec = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'repos'
        managed = True
        unique_together = ('owner', 'name')

    def __str__(self):
        return f"{self.owner}/{self.name}"

class Skill(models.Model):
    name = models.CharField(max_length=100, unique=True)
    type = models.CharField(
        max_length=50,
        choices=SkillType.choices,
        null=True,
        blank=True
    )

    class Meta:
        db_table = 'skills'
        managed = True

    def __str__(self):
        return self.name

# 3. Dependent Models

class Module(models.Model):
    repo = models.ForeignKey(Repo, on_delete=models.CASCADE, related_name='modules')
    name = models.CharField(max_length=255, null=True, blank=True)
    dir_path = models.CharField(max_length=512, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    risk_score = models.FloatField(null=True, blank=True)
    time_created = models.DateTimeField(auto_now_add=True)
    last_update = models.DateTimeField(null=True, blank=True)
    recs = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'modules'
        indexes = [
            models.Index(fields=['name'], name='idx_modules_name'),
        ]
        unique_together = ('repo', 'name')
        managed = True

    def __str__(self):
        return self.name if self.name else "Unnamed Module"

class File(models.Model):
    module_id = models.ForeignKey(Module, on_delete=models.CASCADE, related_name='files', db_column='module_id')
    file_path = models.CharField(max_length=512)
    checksum = models.CharField(max_length=255, null=True, blank=True)
    line_count = models.IntegerField(null=True, blank=True)
    ast_summary = models.JSONField(null=True, blank=True)
    
    # Brain File Metrics
    inbound_coupling = models.IntegerField(default=0)
    module_density = models.FloatField(default=0.0)
    loc_count = models.IntegerField(default=0)
    is_brain_file = models.BooleanField(default=False)

    # Structural Complexity Metrics
    max_nesting_depth = models.IntegerField(default=0)
    max_inheritance_depth = models.IntegerField(default=0)
    structural_risk_score = models.IntegerField(default=0)

    class Meta:
        db_table = 'files'
        managed = True

    def __str__(self):
        return self.file_path

class Review(models.Model):
    engineer = models.ForeignKey(Engineer, on_delete=models.SET_NULL, null=True, related_name='reviews')
    lines = models.IntegerField(null=True, blank=True)
    file_path = models.CharField(max_length=512, null=True, blank=True)
    message = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'reviews'
        managed = True

# 4. Join Tables / Complex Relationships



class ModuleSkill(models.Model):
    module = models.ForeignKey(Module, on_delete=models.CASCADE)
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    score = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = 'module_skills'
        unique_together = ('module', 'skill')
        managed = True

class EngineerSkill(models.Model):
    engineer = models.ForeignKey(Engineer, on_delete=models.CASCADE)
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    score = models.FloatField(null=True, blank=True)
    last_used = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'engineer_skills'
        unique_together = ('engineer', 'skill')
        managed = True

class FileDependency(models.Model):
    importer_file = models.ForeignKey(File, on_delete=models.CASCADE, related_name='dependencies_imported')
    resolved_file = models.ForeignKey(File, on_delete=models.SET_NULL, null=True, blank=True, related_name='imported_by')
    external_package_id = models.IntegerField(null=True, blank=True)
    dependency_type = models.CharField(
        max_length=50,
        choices=DependencyType.choices,
        null=True,
        blank=True
    )
    raw_import_statement = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = 'file_dependencies'
        managed = True

class FileOwnershipMetric(models.Model):
    file = models.ForeignKey(File, on_delete=models.CASCADE)
    engineer = models.ForeignKey(Engineer, on_delete=models.CASCADE)
    lines_owned = models.IntegerField(default=0)
    lines_owned_percentage = models.FloatField(null=True, blank=True)
    commit_count = models.IntegerField(default=0)
    type = models.CharField(
        max_length=50,
        choices=InteractionType.choices
    )

    class Meta:
        db_table = 'file_ownership_metrics'
        unique_together = ('file', 'engineer', 'type')
        managed = True

class ModuleOwnershipMetric(models.Model):
    module = models.ForeignKey(Module, on_delete=models.CASCADE)
    engineer = models.ForeignKey(Engineer, on_delete=models.CASCADE)
    lines_owned = models.IntegerField(default=0)
    lines_owned_percentage = models.FloatField(null=True, blank=True)
    commit_count = models.IntegerField(default=0)
    type = models.CharField(
        max_length=50,
        choices=InteractionType.choices
    )

    class Meta:
        db_table = 'module_ownership_metrics'
        unique_together = ('module', 'engineer', 'type')
        managed = True

class LineOwnership(models.Model):
    file = models.ForeignKey(File, on_delete=models.CASCADE)
    engineer = models.ForeignKey(Engineer, on_delete=models.CASCADE)
    reviewer = models.ForeignKey(Engineer, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_lines')
    timestamp = models.DateTimeField(null=True, blank=True)
    line_range = IntegerRangeField()
    last_updated_commit = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'line_ownership'
        # Note: Excluding Overlapping ranges using Gist is not directly supported by standard Meta options
        # We might need to add a cleanup migration or Constraint in newer Django versions.
        # But for now, we leave the Exclude constraint to database level (created via SQL or RunSQL migration)
        # or we can use ExclusionConstraint from django.contrib.postgres.constraints
        managed = True
