import pytest

from server.manager.services.provider_thread_chatkit import (
    provider_thread_items,
    provider_thread_page,
)


def test_provider_thread_projects_structured_chatkit_items_without_raw_reasoning():
    thread = {
        "turns": [{
            "startedAt": 1,
            "items": [
                {"id": "u1", "type": "userMessage", "content": [
                    {"type": "text", "text": "检查状态"},
                ]},
                {"id": "r1", "type": "reasoning", "summary": [
                    "先读取状态，再核对日志。",
                ], "content": ["PRIVATE_CHAIN_OF_THOUGHT"]},
                {"id": "c1", "type": "commandExecution",
                 "command": "factortester product-library list",
                 "aggregatedOutput": "98 products", "exitCode": 0,
                 "status": "completed"},
                {"id": "f1", "type": "fileChange", "status": "completed",
                 "changes": [{"path": "report.md", "kind": "update",
                              "diff": "+result"}]},
                {"id": "t1", "type": "mcpToolCall", "server": "factor",
                 "tool": "products", "arguments": {"limit": 20},
                 "result": {"count": 98}, "status": "completed"},
                {"id": "w1", "type": "webSearch", "query": "期货品种",
                 "status": "completed"},
                {"id": "p1", "type": "agentMessage", "phase": "commentary",
                 "text": "正在整理结果。"},
                {"id": "a1", "type": "agentMessage",
                 "phase": "final_answer",
                 "text": "完成。\n\n```bash\nfactortester product-library list\n```"},
            ],
        }],
    }

    items = provider_thread_items(thread, "conversation-1")

    assert [item["type"] for item in items] == [
        "user_message", "workflow", "workflow", "workflow",
        "client_tool_call", "workflow", "workflow", "assistant_message",
    ]
    assert items[1]["workflow"]["type"] == "reasoning"
    assert items[1]["workflow"]["tasks"][0]["content"] == (
        "先读取状态，再核对日志。"
    )
    assert "PRIVATE_CHAIN_OF_THOUGHT" not in repr(items)
    assert items[2]["workflow"]["tasks"][0]["content"] == (
        "```text\n98 products\n```\n\nExit code: 0"
    )
    assert items[2]["workflow"]["summary"] == {
        "title": "factortester product-library list",
    }
    assert items[4]["arguments"] == {"limit": 20}
    assert items[-2]["workflow"]["tasks"][0]["content"] == "正在整理结果。"
    assert items[-1]["content"][0]["text"].startswith("完成。\n\n```bash")
    assert all(item["thread_id"] == "conversation-1" for item in items)


def test_interrupted_provider_turn_has_a_durable_visible_outcome():
    page = provider_thread_page({
        "turns": [{
            "id": "turn-interrupted",
            "status": "interrupted",
            "items": [{
                "id": "user-1", "type": "userMessage", "content": "继续",
            }],
        }],
    }, "conversation-1")

    assert [item["id"] for item in page["items"]] == [
        "turn-interrupted-outcome", "user-1",
    ]
    task = page["items"][0]["workflow"]["tasks"][0]
    assert task["title"] == "Agent turn interrupted"
    assert "new message" in task["content"]


def test_provider_thread_does_not_truncate_long_messages_or_item_count():
    text = "x" * 20_000
    thread = {"turns": [{"items": [
        {"id": f"u{index}", "type": "userMessage", "content": text}
        for index in range(550)
    ]}]}

    items = provider_thread_items(thread, "conversation-long")

    assert len(items) == 550
    assert items[0]["content"][0]["text"] == text


def test_provider_thread_pages_by_complete_turn_and_keeps_cursor_stable():
    turns = [{
        "id": f"turn-{index}",
        "items": [
            {"id": f"u-{index}", "type": "userMessage", "content": f"q{index}"},
            {"id": f"a-{index}", "type": "agentMessage", "text": f"a{index}"},
        ],
    } for index in range(12)]

    latest = provider_thread_page(
        {"turns": turns}, "conversation-page", limit=3,
    )
    assert latest["turn_count"] == 3
    assert latest["has_more"] is True
    assert [item["id"] for item in latest["items"]] == [
        "a-11", "u-11", "a-10", "u-10", "a-9", "u-9",
    ]

    # A newly appended turn must not shift the older-page boundary.
    older = provider_thread_page(
        {"turns": turns + [{"id": "turn-12", "items": []}]},
        "conversation-page",
        limit=3,
        after=latest["after"],
    )
    assert [item["id"] for item in older["items"]] == [
        "a-8", "u-8", "a-7", "u-7", "a-6", "u-6",
    ]

    # ChatKit requests the next page using the final visible item id rather
    # than the opaque page cursor returned by the backend.
    chatkit_older = provider_thread_page(
        {"turns": turns},
        "conversation-page",
        limit=3,
        after=latest["items"][-1]["id"],
    )
    assert [item["id"] for item in chatkit_older["items"]] == [
        "a-8", "u-8", "a-7", "u-7", "a-6", "u-6",
    ]

    oldest = provider_thread_page(
        {"turns": turns}, "conversation-page", limit=2, order="asc",
    )
    assert [item["id"] for item in oldest["items"]] == [
        "u-0", "a-0", "u-1", "a-1",
    ]
    newer = provider_thread_page(
        {"turns": turns}, "conversation-page", limit=2,
        after=oldest["after"], order="asc",
    )
    assert [item["id"] for item in newer["items"]] == [
        "u-2", "a-2", "u-3", "a-3",
    ]
    chatkit_newer = provider_thread_page(
        {"turns": turns}, "conversation-page", limit=2,
        after=oldest["items"][-1]["id"], order="asc",
    )
    assert [item["id"] for item in chatkit_newer["items"]] == [
        "u-2", "a-2", "u-3", "a-3",
    ]

    with pytest.raises(ValueError, match="cursor"):
        provider_thread_page(
            {"turns": turns}, "conversation-page",
            after=latest["after"], order="asc",
        )


def test_provider_thread_preserves_complete_visible_timeline():
    thread = {"turns": [{
        "id": "turn-1",
        "items": [
            {"id": "u1", "type": "userMessage", "content": "question"},
            {"id": "r1", "type": "reasoning", "summary": ["visible summary"],
             "content": ["PRIVATE_CHAIN_OF_THOUGHT"]},
            {"id": "p1", "type": "agentMessage", "phase": "commentary",
             "text": "progress"},
            {"id": "a1", "type": "agentMessage", "phase": "final_answer",
             "text": "answer"},
        ],
    }]}

    timeline = provider_thread_page(thread, "conversation-1", view="timeline")

    assert [item["type"] for item in timeline["items"]] == [
        "assistant_message", "workflow", "workflow", "user_message",
    ]
    assert "PRIVATE_CHAIN_OF_THOUGHT" not in repr(timeline)


def test_progress_without_explicit_title_is_collapsible_process():
    items = provider_thread_items({"turns": [{"items": [{
        "id": "progress-1",
        "type": "agentMessage",
        "phase": "commentary",
        "text": "正在检查页面。\n\n已读取配置，下一步校验。",
    }, {
        "id": "answer-1",
        "type": "agentMessage",
        "phase": "final_answer",
        "text": "完成。",
    }]}]}, "conversation-progress")

    progress = items[0]
    assert progress["type"] == "workflow"
    assert progress["workflow"]["tasks"][0]["content"] == (
        "正在检查页面。\n\n已读取配置，下一步校验。"
    )
    assert "Agent progress" not in repr(progress)


def test_progress_with_explicit_title_uses_expandable_summary():
    items = provider_thread_items({"turns": [{"items": [{
        "id": "progress-titled",
        "type": "agentMessage",
        "phase": "commentary",
        "title": "文档结构已更新",
        "text": "查看服务端 schema 确认新字段要求。",
    }]}]}, "conversation-progress")

    progress = items[0]["workflow"]
    assert progress["summary"] == {"title": "文档结构已更新"}
    assert progress["expanded"] is True
    assert progress["tasks"][0]["content"] == (
        "查看服务端 schema 确认新字段要求。"
    )


def test_progress_does_not_repeat_identical_explicit_title_and_body():
    items = provider_thread_items({"turns": [{"items": [{
        "id": "progress-duplicate",
        "type": "agentMessage",
        "phase": "commentary",
        "title": "完成结构校验",
        "text": "完成结构校验",
    }]}]}, "conversation-progress")

    task = items[0]["workflow"]["tasks"][0]
    assert task["title"] == "完成结构校验"
    assert task["content"] is None


def test_outline_defers_large_process_details_with_stable_turn_cursor():
    thread = {"turns": [{"id": f"turn-{i}", "items": [
        {"id": f"cmd-{i}", "type": "commandExecution", "command": "inspect",
         "aggregatedOutput": "large-output" * 10000, "status": "completed"},
        {"id": f"answer-{i}", "type": "agentMessage", "text": "ok"},
    ]} for i in range(3)]}
    outline = provider_thread_page(thread, "c", view="outline", limit=2)
    command = next(item for item in outline["items"] if item["id"] == "cmd-1")
    assert "large-output" not in repr(outline)
    assert command["details_deferred"] is True
    details = provider_thread_page(thread, "c", limit=1, after=command["detail_after"])
    assert {item["turn_id"] for item in details["items"]} == {"turn-1"}
    assert "large-output" in repr(details)
    assert len([item for item in outline["items"] if item["type"] == "assistant_message"]) == 2
