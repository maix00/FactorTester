from server.manager.services.agent_live_turn_chatkit import (
    active_turn_items,
    merge_active_turn,
)


def test_active_turn_is_visible_before_provider_thread_finishes():
    events = [
        {"sequence": 1, "payload": {
            "method": "item/completed",
            "params": {
                "threadId": "thread-live",
                "item": {
                    "id": "reasoning-1", "type": "reasoning",
                    "summary": ["正在检查研究状态"],
                },
            },
        }},
        {"sequence": 2, "payload": {
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thread-live", "itemId": "answer-live",
                "delta": "当前检查到",
            },
        }},
        {"sequence": 3, "payload": {
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thread-live", "itemId": "answer-live",
                "delta": "以下内容",
            },
        }},
    ]

    items = active_turn_items(events, "conversation-live", "thread-live")
    page = merge_active_turn({
        "items": [{"id": "user-1", "type": "user_message"}],
        "order": "desc",
    }, items)

    assert [item["id"] for item in page["items"]] == [
        "answer-live", "reasoning-1", "user-1",
    ]
    assert page["items"][0]["workflow"]["tasks"][0]["content"] == (
        "当前检查到以下内容"
    )
    assert page["items"][0]["workflow"]["tasks"][0]["status_indicator"] == (
        "loading"
    )


def test_active_turn_ignores_events_from_another_thread():
    events = [{"sequence": 1, "payload": {
        "method": "item/agentMessage/delta",
        "params": {
            "threadId": "thread-other", "itemId": "answer-other",
            "delta": "不属于当前会话",
        },
    }}]

    assert active_turn_items(
        events, "conversation-live", "thread-live",
    ) == []
