import json
from server.manager.services.provider_rollout_history import enrich_turns
from server.manager.services.provider_thread_chatkit import provider_thread_page


def test_history_recovers_tools_in_place_and_defers_outputs(tmp_path):
    path = tmp_path / '.codex/sessions/2026/test.jsonl'
    path.parent.mkdir(parents=True)
    rows = [
        ('event_msg', {'type': 'task_started', 'turn_id': 't1'}),
        ('event_msg', {'type': 'user_message', 'message': 'run'}),
        ('event_msg', {'type': 'agent_message', 'message': 'checking'}),
        ('response_item', {'type': 'reasoning', 'id': 'r1', 'summary': [{'text': 'public summary'}], 'content': 'PRIVATE'}),
        ('response_item', {'type': 'function_call', 'call_id': 'c1', 'name': 'exec_command', 'arguments': '{"cmd":"pwd"}'}),
        ('response_item', {'type': 'function_call_output', 'call_id': 'c1', 'output': 'terminal output'}),
        ('event_msg', {'type': 'user_message', 'message': 'steer'}),
        ('event_msg', {'type': 'agent_message', 'message': 'done'}),
    ]
    path.write_text(''.join(json.dumps({'type': k, 'payload': v})+'\n' for k,v in rows))
    turn = {'id': 't1', 'items': [
        {'id': 'u1', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'run'}]},
        {'id': 'a1', 'type': 'agentMessage', 'text': 'checking'},
        {'id': 'u2', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'steer'}]},
        {'id': 'a2', 'type': 'agentMessage', 'text': 'done'},
    ]}
    thread = {'path': '/workspace/.codex/sessions/2026/test.jsonl', 'turns': [turn]}
    def enrich(turns, outline):
        return enrich_turns(thread, turns, tmp_path, outline=outline)
    full = enrich([turn], False)[0]['items']
    assert [v['id'] for v in full] == ['u1', 'a1', 'r1', 'c1', 'u2', 'a2']
    assert 'PRIVATE' not in json.dumps(full)
    page = provider_thread_page(thread, 'conv', view='outline', enrich=enrich)
    tool = next(v for v in page['items'] if v['id'] == 'c1')
    assert tool['details_deferred'] and 'output' not in tool
    assert tool['display_summary'] == 'pwd'
    assert 'arguments' not in tool
    detail = provider_thread_page(thread, 'conv', after=tool['detail_after'], enrich=enrich)
    assert next(v for v in detail['items'] if v['id'] == 'c1')['output'] == 'terminal output'
    # A partial appended record is ignored until the writer finishes it.
    extra = json.dumps({'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'c2', 'name': 'next'}})
    with path.open('a') as f: f.write(extra)
    assert len(enrich([turn], False)[0]['items']) == 6
    with path.open('a') as f: f.write('\n')
    assert len(enrich([turn], False)[0]['items']) == 7


def test_history_rejects_paths_outside_profile(tmp_path):
    turns = [{'id': 't1', 'items': []}]
    assert enrich_turns({'path': '/workspace/.codex/sessions/../../secret'}, turns, tmp_path) == turns
