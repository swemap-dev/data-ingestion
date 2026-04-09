# GraphQL Queries Reference

Summary of each query in this directory and the data it fetches from the GitHub GraphQL API.

---

## 1. `commit_reviewers.graphql` — `GetCommitReviewers`

**Purpose**: Given a list of commit node IDs, fetches the PR reviewers associated with each commit.

| Field | Description |
|-------|-------------|
| `commit.id` | The commit's global node ID |
| `reviews.author.name/email/login` | Reviewer identity (User or Bot) |
| `reviews.state` | Review state (APPROVED, CHANGES_REQUESTED, etc.) |
| `reviews.submittedAt` | When the review was submitted |

**Variables**: `$ids: [ID!]!` — array of commit node IDs.

---

## 2. `file_content.graphql` — `GetFileContent`

**Purpose**: Fetches the raw text content of a single file at a specific git expression (e.g. `HEAD:path/to/file`).

| Field | Description |
|-------|-------------|
| `text` | The file's text content |
| `oid` | Blob SHA |
| `byteSize` | File size in bytes |
| `isBinary` | Whether the file is binary |

**Variables**: `$owner`, `$repo`, `$expression` (e.g. `"main:src/index.py"`).

---

## 3. `file_content_and_blame.graphql` — `GetFileContentAndBlame`

**Purpose**: Fetches both the file content AND its blame ranges in a single request. Used to get file text + line-level ownership simultaneously.

| Field | Description |
|-------|-------------|
| `content.text` | The file's text content |
| `content.oid` | Blob SHA |
| `content.byteSize` | File size |
| `blame.ranges[].startingLine` | Blame range start line |
| `blame.ranges[].endingLine` | Blame range end line |
| `blame.ranges[].commit.oid` | The commit SHA responsible for those lines |

**Variables**: `$owner`, `$repo`, `$expression`, `$ref` (branch), `$path`.

---

## 4. `merged_prs.graphql` — `MergedPRs`

**Purpose**: Fetches paginated merged pull requests, ordered by most recently updated. Includes the files changed in each PR.

| Field | Description |
|-------|-------------|
| `totalCount` | Total number of merged PRs |
| `nodes[].number` | PR number |
| `nodes[].title` | PR title |
| `nodes[].updatedAt / mergedAt` | Timestamps |
| `nodes[].author.login` | PR author's login |
| `nodes[].files.nodes[].path` | File paths changed in the PR |
| `pageInfo.hasNextPage / endCursor` | Pagination cursor |

**Variables**: `$owner`, `$repo`, `$first` (page size), `$after` (cursor).

---

## 5. `ref_commit.graphql` — `GetRefCommit`

**Purpose**: Resolves a git ref (e.g. `refs/heads/main`) to its current commit SHA and tree SHA. Used to check the latest state of a branch.

| Field | Description |
|-------|-------------|
| `commit.oid` | The commit SHA the ref points to |
| `commit.tree.oid` | The tree SHA of that commit |

**Variables**: `$owner`, `$repo`, `$ref`.

---

## 6. `repository_metadata.graphql` — `RepositoryMetadata`

**Purpose**: Fetches comprehensive metadata about a repository. Used during initialization.

| Field | Description |
|-------|-------------|
| `databaseId` | GitHub's internal database ID |
| `name / nameWithOwner` | Repo name |
| `description / url / homepageUrl` | Basic info |
| `isPrivate / isArchived / isFork` | Repo flags |
| `createdAt / updatedAt / pushedAt` | Timestamps |
| `defaultBranchRef.name` | Default branch (e.g. `main`) |
| `primaryLanguage / languages` | Language info |
| `stargazerCount / forkCount / watchers` | Popularity metrics |
| `issues / pullRequests` (open counts) | Activity metrics |
| `licenseInfo` | License name and SPDX ID |
| `repositoryTopics` | Topic tags |

**Variables**: `$owner`, `$repo`.

---

## 7. `rich_blame.graphql` — `GetRichBlame`

**Purpose**: Fetches file content along with detailed blame data including author identity and line age. This is the primary query for ownership analysis.

| Field | Description |
|-------|-------------|
| `content.text` | File text content |
| `content.oid / byteSize / isBinary` | Blob metadata |
| `blame.ranges[].commit.id` | Commit node ID (for reviewer lookups) |
| `blame.ranges[].commit.oid` | Commit SHA |
| `blame.ranges[].commit.author.name/email` | Line author |
| `blame.ranges[].startingLine / endingLine` | Line range |
| `blame.ranges[].age` | How old the blame range is |

**Variables**: `$owner`, `$repo`, `$ref`, `$path`, `$contentExpr`.

> **Note**: This differs from `file_content_and_blame.graphql` by including author identity and `age` per blame range, and also the commit `id` (node ID) needed for the `commit_reviewers` query.
