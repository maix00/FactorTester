"""
GroupTest settings snapshot persistence endpoints.

/save_group_settings  — save a settings snapshot for a (submission_id, factor_alias) pair
/load_group_settings  — load the saved snapshot
/list_group_settings  — list all saved snapshots for a factor family
/delete_group_settings — delete a saved snapshot

Storage: unified SQLite account-template collections.
"""
import logging, traceback
from flask import request, jsonify
from tools.data.account_manage import (
    load_user_templates,
    save_user_templates,
    new_template_id,
)
from server.services.runtime_state import require_user
from . import sft_bp

_log = logging.getLogger(__name__)

KIND = 'group_settings'


def _snapshot_path_key(factor_alias: str) -> str:
    """Sanitize factor alias for use as a filename key."""
    return str(factor_alias).replace('/', '_').replace('\\', '_') or '_unknown'


@sft_bp.route('/save_group_settings', methods=['POST'])
def save_group_settings():
    """Save a GroupTest settings snapshot.

    Request:
    {
        factor_alias: str,       // factor family key
        name: str,               // human-readable snapshot name (optional)
        config: {
            flatGroups: [...],
            lsConfigs: [...],
            registrations: [...]
        }
    }

    Response:
    {
        success: true,
        saved: { id, name, timestamp, config }
    }
    """
    try:
        username = require_user()
        data = request.get_json() or {}
        factor_alias = str(data.get('factor_alias') or '')
        if not factor_alias:
            return jsonify({'success': False, 'error': '缺少 factor_alias'}), 400

        config = data.get('config') or {}
        name = str(data.get('name') or '').strip()

        snapshots = load_user_templates(
            username, KIND, ff_alias=_snapshot_path_key(factor_alias),
            scope_key='snapshots',
        )

        entry = {
            'id': new_template_id(),
            'name': name or '未命名快照',
            'timestamp': new_template_id(),  # same precision, explicit field
            'config': config,
        }
        snapshots.append(entry)
        save_user_templates(
            username, KIND, snapshots,
            ff_alias=_snapshot_path_key(factor_alias),
            scope_key='snapshots',
        )

        return jsonify({'success': True, 'saved': entry})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


@sft_bp.route('/load_group_settings', methods=['POST'])
def load_group_settings():
    """Load a specific GroupTest settings snapshot by id.

    Request: { factor_alias: str, id: str }

    Response: { success: true, snapshot: { id, name, timestamp, config } }
    """
    try:
        username = require_user()
        data = request.get_json() or {}
        factor_alias = str(data.get('factor_alias') or '')
        snapshot_id = str(data.get('id') or '')
        if not factor_alias:
            return jsonify({'success': False, 'error': '缺少 factor_alias'}), 400
        if not snapshot_id:
            return jsonify({'success': False, 'error': '缺少 snapshot id'}), 400

        snapshots = load_user_templates(
            username, KIND, ff_alias=_snapshot_path_key(factor_alias),
            scope_key='snapshots',
        )

        match = next((s for s in snapshots if str(s.get('id', '')) == snapshot_id), None)
        if match is None:
            return jsonify({'success': False, 'error': f'快照 {snapshot_id} 不存在'}), 404

        return jsonify({'success': True, 'snapshot': match})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


@sft_bp.route('/list_group_settings', methods=['POST'])
def list_group_settings():
    """List all saved GroupTest settings snapshots for a factor family.

    Request: { factor_alias: str }

    Response:
    {
        success: true,
        snapshots: [
            { id, name, timestamp, config_summary: { flatGroups: N, lsConfigs: N, ... } },
            ...
        ]
    }
    """
    try:
        username = require_user()
        data = request.get_json() or {}
        factor_alias = str(data.get('factor_alias') or '')
        if not factor_alias:
            return jsonify({'success': False, 'error': '缺少 factor_alias'}), 400

        snapshots = load_user_templates(
            username, KIND, ff_alias=_snapshot_path_key(factor_alias),
            scope_key='snapshots',
        )

        # Return metadata without full config for listing
        summaries = []
        for s in snapshots:
            cfg = s.get('config', {})
            summaries.append({
                'id': s.get('id', ''),
                'name': s.get('name', ''),
                'timestamp': s.get('timestamp', ''),
                'config_summary': {
                    'flatGroups': len(cfg.get('flatGroups', [])),
                    'lsConfigs': len(cfg.get('lsConfigs', [])),
                    'registrations': len(cfg.get('registrations', [])),
                },
            })

        return jsonify({'success': True, 'snapshots': summaries})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})


@sft_bp.route('/delete_group_settings', methods=['POST'])
def delete_group_settings():
    """Delete a saved GroupTest settings snapshot by id.

    Request: { factor_alias: str, id: str }

    Response: { success: true, deleted_id: str }
    """
    try:
        username = require_user()
        data = request.get_json() or {}
        factor_alias = str(data.get('factor_alias') or '')
        snapshot_id = str(data.get('id') or '')
        if not factor_alias:
            return jsonify({'success': False, 'error': '缺少 factor_alias'}), 400
        if not snapshot_id:
            return jsonify({'success': False, 'error': '缺少 snapshot id'}), 400

        snapshots = load_user_templates(
            username, KIND, ff_alias=_snapshot_path_key(factor_alias),
            scope_key='snapshots',
        )

        new_list = [s for s in snapshots if str(s.get('id', '')) != snapshot_id]
        if len(new_list) == len(snapshots):
            return jsonify({'success': False, 'error': f'快照 {snapshot_id} 不存在'}), 404

        save_user_templates(
            username, KIND, new_list,
            ff_alias=_snapshot_path_key(factor_alias),
            scope_key='snapshots',
        )

        return jsonify({'success': True, 'deleted_id': snapshot_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e), 'traceback': traceback.format_exc()})
