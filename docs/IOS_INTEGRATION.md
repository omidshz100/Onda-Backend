# SwiftUI integration contract

The backend and Jitsi server are necessary but not sufficient by themselves to show a call in the
iOS app. SwiftUI must call the API, store credentials securely and present the Jitsi Meet SDK view.
This repository does not modify the separate iOS project.

## Client responsibilities

1. Register/login and store access/refresh tokens in Keychain, never `UserDefaults`.
2. Send `Authorization: Bearer <access-token>` on protected API calls.
3. Refresh once after a `401`; if rotation fails, clear credentials and return to login.
4. Register both standard and VoIP APNs tokens with `/api/v1/users/me/devices`.
5. Use PushKit and CallKit for production incoming-call presentation.
6. On accept/join, use the returned `server_url`, `room_name` and `token` with the Jitsi Meet
   iOS SDK. Do not construct or sign a Jitsi token on-device.
7. Notify the API on reject, cancel, leave and end so call history remains accurate.

## First end-to-end test

For an initial test without APNs, use two physical devices (or one physical device and a simulator)
and poll `/api/v1/calls/incoming` briefly while the call screen is visible:

1. Create two users and sign in on separate clients.
2. Caller searches for the callee and calls `POST /api/v1/calls`.
3. Callee reads the incoming call and calls its accept endpoint.
4. Both clients use the returned Jitsi credentials to join.
5. Confirm microphone/camera permissions and two-way media.
6. End the call and verify it appears in `/api/v1/calls/history` for both users.

APNs/PushKit should replace polling before TestFlight or production distribution.

## Chat integration contract

1. Search for a user and call `POST /api/v1/chat/conversations/direct` with `recipient_id`.
2. Load the inbox from `GET /api/v1/chat/conversations`; each item includes participants, the last
   message and `unread_count`.
3. Connect to `wss://<api-host>/api/v1/chat/ws?token=<access-token>`. Reconnect with backoff and a
   fresh access token after authentication expiry.
4. Send text through `POST /api/v1/chat/conversations/{id}/messages`. Generate and persist one
   `client_message_id` UUID per local message and reuse it for network retries.
5. Consume `message.created`, `message.delivered` and `messages.read` WebSocket events. A `ping`
   event can be used as a keepalive and receives `pong`.
6. Call the delivered endpoint after the message reaches local storage. Call the read endpoint with
   the newest visible message after the conversation is displayed.
7. Load older messages using the `next_before` value returned by the history endpoint.

Text messages are supported in this first version. Attachments, groups, edits/deletes and end-to-end
encryption are intentionally outside this API version.

## Production considerations

- Pin the API base URL per build configuration and require HTTPS.
- Treat the Jitsi JWT as ephemeral; request a fresh join response instead of persisting it.
- Handle camera/microphone denial, interruption, backgrounding and network transitions.
- Keep CallKit state synchronized with API failures and remote termination.
- Never include the API signing secret, Jitsi signing secret or APNs `.p8` key in the app bundle.
