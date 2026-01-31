from django.shortcuts import render
from ninja import NinjaAPI, Schema

from .models import Repo

api = NinjaAPI()

class UserSchema(Schema):
    username: str
    is_authenticated: bool

class RepoSchema(Schema):
    class Meta:
        model = Repo
        model_fields = ['name', 'url', 'language', 'risk_score', 'recency_score', 'complexity_score', 'size_score', 'maintenance_score', 'total_score']

@api.get("/hello")
def hello_world(request, name: str = 'stranger'):
    return {"greeting": f"Hello, {name}!"}

@api.get("/user", response=UserSchema)
def get_user(request):
    return request.user

@api.get("/repos", response=list[RepoSchema])
def get_repos(request):
    return Repo.objects.all()

@api.post("/repos", response=RepoSchema)
def create_repo(request, payload: RepoSchema):
    repo = Repo.objects.create(**payload.dict())
    return repo
