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
    def from_graphql_response(cls, data: Dict[str, Any]) -> 'RepositoryMetadata':
        def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
            if not dt_str:
                return None
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))

        license_name = None
        if data.get('licenseInfo'):
            license_name = data['licenseInfo'].get('name')

        name_with_owner = data.get('nameWithOwner', '')
        owner = name_with_owner.split('/')[0] if '/' in name_with_owner else ''
        url = data.get('url', '')

        return cls(
            id=data.get('databaseId', 0) or 0,
            name=data.get('name', ''),
            full_name=name_with_owner,
            owner=owner,
            description=data.get('description'),
            url=url,
            clone_url=f"{url}.git" if url else '',
            ssh_url=f"git@github.com:{name_with_owner}.git" if name_with_owner else '',
            html_url=url,
            language=(data.get('primaryLanguage') or {}).get('name'),
            stars=data.get('stargazerCount', 0),
            forks=data.get('forkCount', 0),
            watchers=(data.get('watchers') or {}).get('totalCount', 0),
            open_issues=(data.get('issues') or {}).get('totalCount', 0),
            default_branch=(data.get('defaultBranchRef') or {}).get('name', 'main'),
            is_private=data.get('isPrivate', False),
            is_fork=data.get('isFork', False),
            is_archived=data.get('isArchived', False),
            created_at=parse_datetime(data.get('createdAt')),
            updated_at=parse_datetime(data.get('updatedAt')),
            pushed_at=parse_datetime(data.get('pushedAt')),
            size=0,
            license=license_name,
        )
