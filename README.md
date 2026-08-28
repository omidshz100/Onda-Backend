# Onda Backend

Independent FastAPI backend for the Onda SwiftUI messaging and video-calling app. This repository is
deliberately separate from `../Onda`; it does not generate or modify iOS project files.

The API owns user accounts, short-lived access JWTs, rotating refresh sessions, direct chats,
message receipts, meetings, waiting-room membership, direct-call lifecycle and call history. A self-hosted Jitsi deployment
carries audio/video media. The API only issues short-lived, room-scoped Jitsi tokens to authorized
meeting members.

## Implemented API

- Authentication: register, login, refresh-token rotation, reuse detection and logout.
- Users: profile, user search and standard/VoIP APNs device-token lifecycle.
- Meetings: create, resolve invite code, start, join, waiting-room admit/remove and end.
- Calls: create direct audio/video call, accept, reject, cancel, leave, end and history.
- Chat: direct conversations, idempotent text messages, cursor history, unread counts and
  delivered/read receipts.
- Realtime: JWT-authenticated WebSocket events for new messages and receipt changes.
- Notifications: standard APNs message alerts and standard/VoIP incoming-call alerts when Apple
  credentials are configured.
- Jitsi: exact-room authorization and short-lived participant/moderator JWTs.
- Operations: liveness/readiness probes and OpenAPI documentation.

The OpenAPI document currently exposes 34 paths. Swagger UI is available at
`http://127.0.0.1:8000/docs`. See `docs/IOS_INTEGRATION.md` for the SwiftUI flow and
`docs/ARCHITECTURE.md` for trust boundaries and call sequences.

## Local setup

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/) and PostgreSQL 14+ (or Docker).

```bash
cp .env.example .env
docker compose up -d postgres
uv sync --locked --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Verification:

```bash
uv run ruff check .
uv run pytest
```

Health probes are available at `/api/v1/health/live` and `/api/v1/health/ready`.

## Azure and Jitsi

The `infra/` directory extends the existing `onda-dev-rg` resource group and existing
`onda-api-omid-2026` App Service. It can provision PostgreSQL Flexible Server, Key Vault and a
Linux VM running the official Jitsi Docker stack. Applying that infrastructure can create billable
resources and is intentionally a separate, approval-gated step; see `infra/README.md`.

Never commit `.env`, APNs credentials, private SSH keys or production secrets. Production secrets
are supplied to App Service and the Jitsi VM through Key Vault and managed identities.
