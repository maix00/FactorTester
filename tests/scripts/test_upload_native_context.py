import hashlib
import os
import shlex
import shutil
import subprocess

import pytest

from scripts.server import upload_native_context as upload


@pytest.fixture
def transport(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    destination = tmp_path / "remote directory 'quoted'"
    source.mkdir(); destination.mkdir()
    (source / 'runtime.whl').write_bytes(b'abcdefghijkl')
    commands = tmp_path / 'bin'; commands.mkdir()
    native_sha = shutil.which('sha256sum')
    tool = native_sha or shutil.which('shasum')
    assert tool
    sha = commands / 'sha256sum'
    sha.write_text('#!/bin/sh\nexec '+shlex.quote(tool)+('' if native_sha else ' -a 256')+' "$@"\n')
    sha.chmod(0o700)
    monkeypatch.setenv('PATH', str(commands)+os.pathsep+os.environ['PATH'])
    monkeypatch.setattr(upload.time, 'sleep', lambda _: None)
    original = subprocess.run
    calls, failures = [], {}

    def run(args, *, input, **kwargs):
        assert args[0] == 'fixture-ssh'
        calls.append(input)
        if input is not None and failures.get(input, 0):
            failures[input] -= 1
            return subprocess.CompletedProcess(args, 255, b'', b'transport interrupted')
        return original(['bash', '-c', args[-1]], input=input, **kwargs)

    monkeypatch.setattr(upload.subprocess, 'run', run)
    return source, destination, calls, failures


def test_interrupted_upload_resumes_verified_chunks_without_sending_them_again(transport):
    source, destination, calls, failures = transport
    failures[b'efgh'] = 3
    with pytest.raises(RuntimeError, match='three attempts'):
        upload.upload_context(source, str(destination), ['fixture-ssh'], workers=1, chunk_bytes=4)
    assert list(destination.glob('.chunk-*'))
    assert not (destination / 'runtime.whl').exists()
    calls.clear()
    upload.upload_context(source, str(destination), ['fixture-ssh'], workers=1, chunk_bytes=4)
    assert b'abcd' not in calls and b'ijkl' not in calls
    assert calls.count(b'efgh') == 1
    assert (destination / 'runtime.whl').read_bytes() == b'abcdefghijkl'
    assert not list(destination.glob('.chunk-*'))
    assert not list(destination.glob('*.part.*'))


def test_same_size_corrupt_chunk_is_replaced_instead_of_trusted(transport):
    source, destination, calls, _ = transport
    digest = hashlib.sha256(b'abcdefghijkl').hexdigest()
    (destination / f'.chunk-{digest}-4-000000').write_bytes(b'xxxx')
    (destination / f'.chunk-{digest}-4-000001').write_bytes(b'efgh')
    upload.upload_context(source, str(destination), ['fixture-ssh'], workers=1, chunk_bytes=4)
    assert b'abcd' in calls and b'efgh' not in calls
    assert (destination / 'runtime.whl').read_bytes() == b'abcdefghijkl'


def test_verified_complete_file_skips_payload_and_cleans_interrupted_chunks(transport):
    source, destination, calls, _ = transport
    (destination / 'runtime.whl').write_bytes(b'abcdefghijkl')
    digest = hashlib.sha256(b'abcdefghijkl').hexdigest()
    (destination / f'.chunk-{digest}-4-000000').write_bytes(b'abcd')
    upload.upload_context(source, str(destination), ['fixture-ssh'], workers=1, chunk_bytes=4)
    assert all(data is None for data in calls)
    assert not list(destination.glob('.chunk-*'))


def test_bad_transport_bytes_do_not_publish_partial_file(transport, monkeypatch):
    source, destination, _, _ = transport
    normal = upload.subprocess.run
    def corrupt(args, *, input, **kwargs):
        return normal(args, input=b'wrong' if input is not None else None, **kwargs)
    monkeypatch.setattr(upload.subprocess, 'run', corrupt)
    with pytest.raises(subprocess.CalledProcessError):
        upload.upload_context(source, str(destination), ['fixture-ssh'], workers=1, chunk_bytes=4)
    assert not (destination / 'runtime.whl').exists()
    assert not list(destination.glob('*.part.*'))


def test_chunk_memory_is_bounded(transport):
    source, destination, _, _ = transport
    with pytest.raises(ValueError, match='budget'):
        upload.upload_context(source, str(destination), ['fixture-ssh'], chunk_bytes=4*1024*1024+1)


def test_lost_acknowledgement_with_parallel_workers_does_not_corrupt_output(transport, monkeypatch):
    source, destination, _, _ = transport
    normal = upload.subprocess.run
    lost = [False]
    def lose_ack(args, *, input, **kwargs):
        result = normal(args, input=input, **kwargs)
        if input == b'abcd' and not lost[0]:
            lost[0] = True
            return subprocess.CompletedProcess(args, 255, b'', b'acknowledgement lost')
        return result
    monkeypatch.setattr(upload.subprocess, 'run', lose_ack)
    upload.upload_context(source, str(destination), ['fixture-ssh'], workers=2, chunk_bytes=4)
    assert lost[0]
    assert (destination / 'runtime.whl').read_bytes() == b'abcdefghijkl'
    assert not list(destination.glob('*.part.*'))
    assert not list(destination.glob('.chunk-*'))
