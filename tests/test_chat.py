from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from starlette.websockets import WebSocketDisconnect

from app.api.v1 import chat as chat_api
from app.main import app
from tests.conftest import TestSessionFactory
from tests.helpers import authorization, register_user


async def test_direct_chat_delivery_read_history_and_idempotency(client: AsyncClient) -> None:
    sender = await register_user(
        client, email="chat-sender@example.com", display_name="Chat Sender"
    )
    recipient = await register_user(
        client, email="chat-recipient@example.com", display_name="Chat Recipient"
    )
    outsider = await register_user(
        client, email="chat-outsider@example.com", display_name="Chat Outsider"
    )
    sender_headers = authorization(sender["access_token"])
    recipient_headers = authorization(recipient["access_token"])
    outsider_headers = authorization(outsider["access_token"])
    recipient_profile = await client.get("/api/v1/users/me", headers=recipient_headers)

    created = await client.post(
        "/api/v1/chat/conversations/direct",
        headers=sender_headers,
        json={"recipient_id": recipient_profile.json()["id"]},
    )
    assert created.status_code == 201, created.text
    conversation = created.json()
    conversation_id = conversation["id"]
    assert conversation["unread_count"] == 0
    assert {participant["display_name"] for participant in conversation["participants"]} == {
        "Chat Sender",
        "Chat Recipient",
    }

    duplicate_conversation = await client.post(
        "/api/v1/chat/conversations/direct",
        headers=sender_headers,
        json={"recipient_id": recipient_profile.json()["id"]},
    )
    assert duplicate_conversation.json()["id"] == conversation_id

    client_message_id = str(uuid4())
    sent = await client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        headers=sender_headers,
        json={"body": "  Hello from Onda  ", "client_message_id": client_message_id},
    )
    assert sent.status_code == 201, sent.text
    message = sent.json()
    assert message["body"] == "Hello from Onda"
    assert message["delivered_at"] is None
    assert message["read_at"] is None

    retried = await client.post(
        f"/api/v1/chat/conversations/{conversation_id}/messages",
        headers=sender_headers,
        json={"body": "Hello from Onda", "client_message_id": client_message_id},
    )
    assert retried.json()["id"] == message["id"]

    recipient_conversations = await client.get(
        "/api/v1/chat/conversations", headers=recipient_headers
    )
    assert recipient_conversations.status_code == 200
    assert recipient_conversations.json()[0]["unread_count"] == 1

    forbidden = await client.get(
        f"/api/v1/chat/conversations/{conversation_id}/messages", headers=outsider_headers
    )
    assert forbidden.status_code == 404

    delivered = await client.post(
        f"/api/v1/chat/messages/{message['id']}/delivered", headers=recipient_headers
    )
    assert delivered.status_code == 200
    assert delivered.json()["message"]["delivered_at"] is not None

    read = await client.post(
        f"/api/v1/chat/conversations/{conversation_id}/read",
        headers=recipient_headers,
        json={"up_to_message_id": message["id"]},
    )
    assert read.status_code == 200
    assert read.json()["updated_count"] == 1

    history = await client.get(
        f"/api/v1/chat/conversations/{conversation_id}/messages", headers=sender_headers
    )
    assert history.status_code == 200
    assert [item["id"] for item in history.json()["items"]] == [message["id"]]
    assert history.json()["items"][0]["read_at"] is not None

    after_read = await client.get("/api/v1/chat/conversations", headers=recipient_headers)
    assert after_read.json()[0]["unread_count"] == 0


async def test_chat_rejects_self_conversation_and_blank_message(client: AsyncClient) -> None:
    user = await register_user(client, email="self-chat@example.com", display_name="Self Chat")
    headers = authorization(user["access_token"])
    profile = await client.get("/api/v1/users/me", headers=headers)
    self_conversation = await client.post(
        "/api/v1/chat/conversations/direct",
        headers=headers,
        json={"recipient_id": profile.json()["id"]},
    )
    assert self_conversation.status_code == 422

    peer = await register_user(client, email="blank-peer@example.com", display_name="Blank Peer")
    peer_profile = await client.get(
        "/api/v1/users/me", headers=authorization(peer["access_token"])
    )
    conversation = await client.post(
        "/api/v1/chat/conversations/direct",
        headers=headers,
        json={"recipient_id": peer_profile.json()["id"]},
    )
    blank = await client.post(
        f"/api/v1/chat/conversations/{conversation.json()['id']}/messages",
        headers=headers,
        json={"body": "   "},
    )
    assert blank.status_code == 422


def test_chat_websocket_requires_jwt_and_answers_ping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat_api, "AsyncSessionFactory", TestSessionFactory)
    with TestClient(app, base_url="https://testserver") as sync_client:
        registered = sync_client.post(
            "/api/v1/auth/register",
            json={
                "email": "websocket@example.com",
                "display_name": "WebSocket User",
                "password": "SecurePassword123",
            },
        )
        assert registered.status_code == 201, registered.text

        with pytest.raises(WebSocketDisconnect) as rejected:
            with sync_client.websocket_connect("/api/v1/chat/ws"):
                pass
        assert rejected.value.code == 4401

        token = registered.json()["access_token"]
        with sync_client.websocket_connect(f"/api/v1/chat/ws?token={token}") as websocket:
            connected = websocket.receive_json()
            assert connected["type"] == "connected"
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json()["type"] == "pong"
