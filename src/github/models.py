from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class RepositoryMetadata:
    id: int
    name: str
    full_name: str
    owner: str
    description: Optional[str]
    url: str
    clone_url: str
    ssh_url: str
    html_url: str
    language: Optional[str]
    stars: int
    forks: int
    watchers: int
    open_issues: int
    default_branch: str
    is_private: bool
    is_fork: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    pushed_at: Optional[datetime]
    size: int
    license: Optional[str]
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> 'RepositoryMetadata':
        def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
            if not dt_str:
                return None
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        
        license_name = None
        if data.get('license'):
            license_name = data['license'].get('name')
        
        return cls(
            id=data['id'],
            name=data['name'],
            full_name=data['full_name'],
            owner=data['owner']['login'],
            description=data.get('description'),
            url=data['url'],
            clone_url=data['clone_url'],
            ssh_url=data['ssh_url'],
            html_url=data['html_url'],
            language=data.get('language'),
            stars=data.get('stargazers_count', 0),
            forks=data.get('forks_count', 0),
            watchers=data.get('watchers_count', 0),
            open_issues=data.get('open_issues_count', 0),
            default_branch=data.get('default_branch', 'main'),
            is_private=data.get('private', False),
            is_fork=data.get('fork', False),
            is_archived=data.get('archived', False),
            created_at=parse_datetime(data.get('created_at')),
            updated_at=parse_datetime(data.get('updated_at')),
            pushed_at=parse_datetime(data.get('pushed_at')),
            size=data.get('size', 0),
            license=license_name
        )

