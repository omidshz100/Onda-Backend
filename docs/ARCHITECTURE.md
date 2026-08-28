# Backend architecture

## Components and trust boundaries

```text
SwiftUI app
  | HTTPS + Onda access JWT
  v
Azure App Service: FastAPI control plane
  |-- PostgreSQL Flexible Server (users, conversations, messages, meetings, calls, sessions)
  |-- Key Vault via managed identity (database/API/Jitsi secrets)
  |-- APNs over HTTP/2 (optional incoming-call notification)
  `-- issues a short-lived, room-scoped Jitsi JWT
                              |
                              v
                    Self-hosted Jitsi VM
                    HTTPS/WSS + UDP media
```

FastAPI is the source of truth for identity, authorization and call state. It does not proxy audio
or video. Clients connect directly to Jitsi after FastAPI confirms membership and issues a Jitsi
token. PostgreSQL is never public to the iOS client.

## Authentication and security

- Passwords are hashed with Argon2; plaintext passwords are never stored.
- Access tokens are signed JWTs with issuer, audience, expiry, subject, type and unique ID claims.
- Refresh tokens are opaque random values. Only their hashes are stored, and each use rotates the
  token. Reuse revokes the entire refresh-token family.
- Authentication endpoints have a per-IP in-memory development rate limiter. Production should
  additionally use an Azure edge/WAF rate limit if public traffic grows.
- Meeting JWTs expire quickly, name one exact room and carry moderator/member affiliation.
- Waiting-room members cannot obtain a Jitsi token until the host admits them.
- Secrets are provided through environment variables locally and Key Vault references in Azure.
- TLS terminates at App Service and the Jitsi reverse proxy. Jitsi media uses UDP 10000.

## Direct message sequence

1. A client creates or resolves a direct conversation with one recipient.
2. The sender posts a text message with a client-generated UUID. Reusing that UUID returns the
   existing message instead of inserting a duplicate after a retry.
3. PostgreSQL commits the message before FastAPI emits `message.created` to authenticated WebSocket
   connections and schedules an optional APNs alert.
4. The recipient marks the message delivered and later marks the conversation read through a chosen
   message. Receipt events are emitted to the sender.
5. Message history uses a time cursor and is only visible to conversation members.

The current realtime connection registry is process-local and matches the single App Service
instance used for this development deployment. Before horizontally scaling to multiple instances,
replace its event fan-out with Azure Cache for Redis or another shared pub/sub layer.

## Direct call sequence

1. Caller creates a direct call with `audio` or `video` media type.
2. FastAPI creates the meeting, host membership, callee waiting membership and ringing call in one
   database transaction.
3. If configured, FastAPI sends an APNs VoIP notification after the transaction commits.
4. Callee accepts. FastAPI admits the callee and returns meeting/Jitsi join credentials.
5. Caller requests join credentials and both clients connect directly to the same Jitsi room.
6. Client leave/end actions update participant timestamps, call state and call history.
7. Unanswered ringing calls expire lazily after the configured timeout.

## Data model

- `users`, `refresh_sessions`, `devices`
- `conversations`, `conversation_members`, `chat_messages`
- `meetings`, `meeting_members`
- `calls`, `call_participants`

All externally visible records use UUIDs. A message can also carry a client-generated UUID for
idempotent retries. Invite codes and Jitsi room names are distinct so a
human-friendly invite cannot become an authorization credential by itself.
