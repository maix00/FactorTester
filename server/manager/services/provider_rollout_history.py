"""Recover omitted public tool activity from the Provider's own rollout.

Only offsets are cached; outputs are read for the requested turns. No second
transcript is persisted, and private reasoning content is never projected.
"""
from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path

_LOCK = threading.RLock()
_INDEXES = OrderedDict()


def _index(path):
    stat = path.stat()
    key = str(path)
    index = _INDEXES.pop(key, None)
    if index is None or index['inode'] != stat.st_ino or stat.st_size < index['offset']:
        index = {'inode': stat.st_ino, 'offset': 0, 'turn': '', 'turns': {}}
    with path.open('rb') as stream:
        stream.seek(index['offset'])
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line or not line.endswith(b'\n'):
                break  # An active writer may not have finished this record.
            index['offset'] = stream.tell()
            try:
                row = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            payload = row.get('payload') or {}
            if row.get('type') == 'turn_context' or (
                row.get('type') == 'event_msg' and payload.get('type') == 'task_started'
            ):
                index['turn'] = payload.get('turn_id') or index['turn']
            if index['turn'] and row.get('type') in {'event_msg', 'response_item'}:
                index['turns'].setdefault(index['turn'], []).append(offset)
    _INDEXES[key] = index
    while len(_INDEXES) > 16:
        _INDEXES.popitem(last=False)
    return index


def enrich_turns(thread, turns, workspace_root, *, outline=False):
    """Supplement canonical messages, preserving their IDs and actual order."""
    raw_path = str(thread.get('path') or '')
    prefix = '/workspace/.codex/sessions/'
    if not raw_path.startswith(prefix):
        return turns
    root = (Path(workspace_root) / '.codex' / 'sessions').resolve()
    path = (root / raw_path[len(prefix):]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return turns
    with _LOCK:
        index = _index(path)
        result = []
        with path.open('rb') as stream:
            for turn in turns:
                offsets = index['turns'].get(turn.get('id'), [])
                canonical = list(turn.get('items') or [])
                ordered, used, calls = [], set(), {}
                for offset in offsets:
                    stream.seek(offset)
                    row = json.loads(stream.readline())
                    item = row.get('payload') or {}
                    kind = item.get('type')
                    if row.get('type') == 'event_msg' and kind in {'agent_message', 'user_message'}:
                        wanted = 'agentMessage' if kind == 'agent_message' else 'userMessage'
                        for n, candidate in enumerate(canonical):
                            if n in used or candidate.get('type') != wanted:
                                continue
                            content = candidate.get('text', candidate.get('content', ''))
                            if isinstance(content, list):
                                content = ''.join(p.get('text', '') for p in content if isinstance(p, dict))
                            if content == item.get('message'):
                                used.add(n)
                                ordered.append(candidate)
                                break
                    elif row.get('type') == 'response_item' and kind == 'function_call':
                        call_id = item.get('call_id')
                        if not call_id or call_id in calls:
                            continue
                        # Prefer a native item if the Provider already projects it.
                        existing = next((v for v in canonical if call_id in {v.get('id'), v.get('callId'), v.get('call_id')}), None)
                        value = dict(existing) if existing else {'id': call_id, 'type': 'dynamicToolCall',
                            'tool': item.get('name') or '工具调用', 'status': 'inProgress',
                            'arguments': '' if outline else item.get('arguments', '')}
                        calls[call_id] = value
                        ordered.append(value)
                    elif row.get('type') == 'response_item' and kind == 'function_call_output':
                        value = calls.get(item.get('call_id'))
                        if value is not None:
                            value['status'] = 'completed'
                            if not outline:
                                value['output'] = item.get('output', '')
                    elif row.get('type') == 'response_item' and kind == 'reasoning' and item.get('summary'):
                        ordered.append({'id': item.get('id') or f'rollout-summary-{offset}',
                            'type': 'reasoning', 'summary': item['summary']})
                seen = {v.get('id') for v in ordered}
                ordered.extend(v for v in canonical if v.get('id') not in seen)
                result.append({**turn, 'items': ordered})
        return result
