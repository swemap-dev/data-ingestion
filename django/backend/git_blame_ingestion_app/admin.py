from django.contrib import admin
from .models import Engineer, Repo, Skill, Module, File, Review, ModuleContribution, FileContribution, ModuleSkill, EngineerSkill, FileDependency

# Register your models here.
admin.site.register(Engineer)
admin.site.register(Repo)
admin.site.register(Skill)
admin.site.register(Module)
admin.site.register(File)
admin.site.register(Review)
admin.site.register(ModuleContribution)
admin.site.register(FileContribution)
admin.site.register(ModuleSkill)
admin.site.register(EngineerSkill)
admin.site.register(FileDependency)