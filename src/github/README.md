## Usage

### GitHub Repository Metadata

```python
from src.github import GitHubClient

client = GitHubClient()
repo = client.get_repository('owner', 'repo-name')
```

### GitHub File Contents

```python
from src.github import GitHubClient, FileContentsService

client = GitHubClient()
service = FileContentsService(client)
contents = service.get_recursive_file_contents('owner', 'repo-name')
```