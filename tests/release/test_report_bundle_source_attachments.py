import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import zipfile

import pytest

from tools.cli.release.research_reporting.authoring.tree_model import initialize_tree,add_component,add_binding,load_snapshot
from tools.cli.release.research_reporting.authoring.tree_bundle import bundle_from_snapshot,validate_report_bundle,import_report_bundle
from tools.cli.release.research_reporting.authoring.bundle_source_attachments import git_blob_digest
from tools.cli.release.research_reporting.public_research.projection import build_upload_projection
from server.jobs.storage.couchdb_research_publication import prepare_projection,prepare_authoring


def source_tree(tmp_path, *, missing=False):
    profile=tmp_path/'profile';root=profile/'research'/'report'
    initialize_tree(package_root=root,branch_id='main',report_id='report-1',title='Source')
    add_component(package_root=root,branch_id='main',component_id='chapter',kind='chapter',title='Chapter',parent_id=None,body='',content=None,display_kind='')
    add_component(package_root=root,branch_id='main',component_id='entry',kind='entry',title='',parent_id='chapter',
        body='[Legacy script](research/momentum_factor/scripts/missing.py)' if missing else 'Frozen factor source',content=None,display_kind='')
    raw=b'raise AssertionError("report quoting must not execute this file")\n'
    if not missing:
        worktree=profile/'factor-worktree';worktree.mkdir();(worktree/'.git').mkdir();(worktree/'family.py').write_bytes(raw)
        add_binding(package_root=root,branch_id='main',component_id='entry',binding={'binding_id':'frozen-source','kind':'factor',
            'target_ref':'factor:v1:alice:Family:Formula:'+ '1'*40+':'+ '2'*40,'label':'Factor',
            'data':{'relative_path':'family.py','blob_hash':git_blob_digest(raw),'revision':'1'*40}})
    return root,load_snapshot(package_root=root,branch_id='main'),raw


def import_bundle(tmp_path,snapshot,payload):
    head=snapshot['head'];target=tmp_path/'fresh-cache'
    imported=import_report_bundle(payload=payload,expected_sha256=hashlib.sha256(payload).hexdigest(),package_root=target,
        branch_id='main',report_id=head['report_id'],source_generation=head['generation'],source_root_ref=head['root_ref'])
    return target,imported


def test_frozen_source_quote_survives_without_the_original_git_worktree(tmp_path):
    root,snapshot,raw=source_tree(tmp_path)
    before=build_upload_projection(snapshot)
    payload=bundle_from_snapshot(snapshot,package_root=root,branch_id='main');sha=hashlib.sha256(payload).hexdigest();h=snapshot['head']
    manifest,files=validate_report_bundle(payload=payload,expected_sha256=sha,report_id=h['report_id'],source_generation=h['generation'],source_root_ref=h['root_ref'])
    assert manifest['schema_version']==3 and len(manifest['source_attachments'])==1 and raw in files.values()
    prepared=prepare_projection(before,report_id=h['report_id'])[0]
    prepare_authoring({'sha256':sha,'root_ref':h['root_ref'],'content_base64':base64.b64encode(payload).decode()},
        report_id=h['report_id'],generation=h['generation'],branch_ref='main',projection=prepared)
    target,imported=import_bundle(tmp_path,snapshot,payload)
    shutil.rmtree(root.parents[1]/'factor-worktree')
    after=build_upload_projection(load_snapshot(package_root=target,branch_id='main'))
    assert after['attachments']==before['attachments']
    assert after['related_objects']==before['related_objects']
    source_file=next((target/'branches/main/authoring/selected-sources').iterdir())
    source_file.write_bytes(b'changed outside the versioned source')
    with pytest.raises(ValueError,match='cache bytes differ'):
        build_upload_projection(load_snapshot(package_root=target,branch_id='main'))


def test_source_quote_must_match_a_frozen_binding_before_materialization(tmp_path):
    root,snapshot,_raw=source_tree(tmp_path)
    payload=bundle_from_snapshot(snapshot,package_root=root,branch_id='main')
    output=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as old,zipfile.ZipFile(output,'w') as archive:
        for name in old.namelist():
            raw=old.read(name)
            if name=='manifest.json':
                value=json.loads(raw);value['source_attachments'][0]['git_blob']='f'*40;raw=json.dumps(value).encode()
            archive.writestr(name,raw)
    with pytest.raises(ValueError,match='attachment identity differs'):
        import_bundle(tmp_path,snapshot,output.getvalue())
    assert not (tmp_path/'fresh-cache').exists()


def test_missing_legacy_link_is_explicit_and_never_reads_an_external_file(tmp_path):
    root,snapshot,_raw=source_tree(tmp_path,missing=True)
    with pytest.raises(ValueError,match='resource is unavailable'):
        bundle_from_snapshot(snapshot,package_root=root,branch_id='main')
    payload=bundle_from_snapshot(snapshot,package_root=root,branch_id='main',allow_unavailable_links=True)
    sha=hashlib.sha256(payload).hexdigest();h=snapshot['head']
    manifest,_files=validate_report_bundle(payload=payload,expected_sha256=sha,report_id=h['report_id'],source_generation=h['generation'],source_root_ref=h['root_ref'])
    assert manifest['unavailable_links']==[{'target':'research/momentum_factor/scripts/missing.py','filename':'missing.py','reason':'source_unavailable'}]
    projection=prepare_projection(build_upload_projection(snapshot),report_id=h['report_id'])[0]
    assert projection['local_resources'][0]['available'] is False
    prepare_authoring({'sha256':sha,'root_ref':h['root_ref'],'content_base64':base64.b64encode(payload).decode()},
        report_id=h['report_id'],generation=h['generation'],branch_ref='main',projection=projection)
    target,_loaded=import_bundle(tmp_path,snapshot,payload)
    restored=load_snapshot(package_root=target,branch_id='main')
    assert build_upload_projection(restored)['local_resources'][0]['available'] is False
    again=bundle_from_snapshot(restored,package_root=target,branch_id='main')
    assert again
