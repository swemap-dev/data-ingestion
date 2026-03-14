from django.contrib import admin
from .models import (
    Engineer, Repo, Skill, Module, File, Review,
    ModuleSkill, EngineerSkill, FileDependency, LineOwnership, FileOwnershipMetric,
    ModuleOwnershipMetric, PullRequest, PullRequestFile
)

# Register your models here.
# Register your models here.
admin.site.register(Engineer)
admin.site.register(Repo)
admin.site.register(Skill)
admin.site.register(Module)
admin.site.register(File)
admin.site.register(Review)
admin.site.register(ModuleSkill)
admin.site.register(EngineerSkill)
admin.site.register(FileDependency)
admin.site.register(LineOwnership)
admin.site.register(FileOwnershipMetric)
admin.site.register(ModuleOwnershipMetric)
admin.site.register(PullRequest)
admin.site.register(PullRequestFile)