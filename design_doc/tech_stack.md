# Tech Stack Design: Enterprise MVP

## Core Philosophy
To achieve an "Enterprise-level MVP" that is "Plug-and-Play", the architecture prioritizes **portability** (Docker), **robustness** (Django/Postgres), and **distributed processing** (Celery/Redis) while maintaining a single cohesive codebase for ease of deployment.

## 1. The Stack Overview

| Layer | Technology | Rationale |
| :--- | :--- | :--- |
| **Backend Framework** | **Django** + **Django Ninja** | Django provides the batteries (ORM, Auth, Admin). **Django Ninja** is chosen over DRF because it uses standard Python type hints (Pydantic), is faster, and auto-generates interactive API docs (Swagger UI)—crucial for enterprise integrations. |
| **Database** | **PostgreSQL** | Industry standard. Handles the complex relational data (users -> repos -> files -> lines -> authors) and JSONB fields for flexibility better than any other SQL DB. |
| **Async Task Queue** | **Celery** + **Redis** | Mandatory replacement for `threading`. Redis acts as the broker. Celery manages the workers. This allows you to scale: one container for the web server, separate containers for heavy ingestion workers. |
| **Frontend** | **React** (via **Vite**) | A Single Page Application (SPA) allows for the "Tech-forward" and dynamic "Dashboard" experience required. Vite is chosen for speed and simplicity over Next.js, as SEO is not a priority for a private enterprise dashboard. |
| **Deployment** | **Docker Compose** | The ultimate "Plug-and-Play" artifact. You ship a `docker-compose.yml` file. The customer runs `docker compose up -d` and the entire stack (Web, Worker, DB, Redis, Frontend) spins up. |

## 2. Infrastructure & Orchestration

### MVP Phase (Current Goal)
*   Container 1: `web` (Django + Ninja API).
*   Container 2: `worker` (Celery - Ingestion Jobs).
*   Container 3: `beat` (Celery - Scheduled Polling).
*   Container 4: `db` (PostgreSQL).
*   Container 5: `redis` (Broker/Cache).
*   Container 6: `frontend` (Nginx serving React static build).

## 3. Detailed Component Choices

### API Layer: Django Ninja vs DRF
*   **Selection**: **Django Ninja**.
*   **Why**: Your data ingestion logic handles complex JSON structures from GitHub. Pydantic (used by Ninja) is significantly better at parsing and validating these nested structures than DRF Serializers.

### Authentication
*   **Selection**: **JWT (JSON Web Tokens)** via `django-ninja-jwt`.
*   **Why**: Stateless auth is easier for the React Frontend to handle.

### Frontend UI Library
*   **Selection**: **Tailwind CSS** + **shadcn/ui**.

### Database Strategy: Pure Postgres over Hybrid (Supabase RLS)
*   **Selection**: **Standard PostgreSQL Interface + Django Logic**.
*   **Alternative Analyzed**: "Hybrid Approach" (Supabase RLS for security, Django for logic).
*   **Why we REJECTED the Hybrid approach**:
    1.  **Complexity**: Django assumes it controls database access. To use RLS, every single query would need to be wrapped in a transaction that sets the current user context (`SET app.current_user_id = '...'`). This fights against the Django ORM.
    2.  **Orchestration Cost**: You would need to synchronize Authentication. Using Supabase Auth means you have to sync users to Django Users constantly.
    3.  **Deployment**: On-premise deployment of the full Supabase Auth stack is difficult. Standard Django Auth works everywhere instantly.

### Async Processing: Redis + Celery
*   **Selection**: **Redis + Celery**.
*   **Why**: Realtime is for notifications, not persistent job management.

## 4. Development Workflow Changes

1.  **Repo Structure**: Monorepo.
    ```text
    /
    ├── backend/     # Django Project
    ├── frontend/    # React Project
    ├── docker-compose.yml
    └── README.md
    ```
