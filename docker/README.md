# docker/

Container definitions arrive in two steps:

- **Phase 2/3**: `compose.dev.yaml` for local infrastructure only (PostgreSQL, Qdrant, Redis).
- **Phase 14**: full stack (`backend`, `frontend`, `worker`, databases) via `docker compose up`.
