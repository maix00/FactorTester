"""Disposable, process-shared Arrow buffers. No platform or Nautilus dependency.

The cache is scoped by its trusted host, never by an untrusted request. IPC is
uncompressed for mmap readers. File/revision keys describe cache freshness, not
an immutable historical provenance guarantee. Accounts/strategy state do not
belong here.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import errno
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Iterator, Sequence


CACHE_FORMAT_VERSION = 4  # v3 retains metadata; v4 shares source inode aliases


class CacheBusy(RuntimeError):
    pass


class CacheLimit(RuntimeError):
    pass


@contextmanager
def _lock(path: Path, timeout: float = 5.0):
    handle = path.open('a+b')
    deadline = time.monotonic() + timeout
    locked = False
    try:
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    handle.seek(0)
                    if path.stat().st_size == 0:
                        handle.write(b'\0'); handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                if time.monotonic() >= deadline:
                    raise CacheBusy('shared data resource is busy') from exc
                time.sleep(0.01)
        yield
    finally:
        if locked:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


@dataclass(frozen=True, slots=True)
class CacheScope:
    role: str
    authority: str
    owner: str
    device: str

    def __post_init__(self):
        if self.role not in {'server', 'client'} or any(
            not isinstance(v, str) or not v.strip()
            for v in (self.authority, self.owner, self.device)
        ):
            raise ValueError('explicit cache authority, owner and device required')

    @property
    def key(self):
        return sha256(json.dumps([self.role, self.authority, self.owner, self.device]).encode()).hexdigest()


class SharedColumnarCache:
    """Share decoded immutable row groups; bound disk and concurrent consumers.

    Large row groups are decoded incrementally into fixed 4096-row IPC chunks. Active mmap readers survive eviction on POSIX; on Windows pinned
    files are skipped. In either case readers never observe a partially written
    entry. Cache files are derived data and may be deleted when not in use.
    """
    def __init__(self, root: Path, scope: CacheScope, *, max_bytes=512*1024**2,
                 max_entry_bytes=64*1024**2, max_entries=256, consumers=4, timeout=5.0):
        if (type(max_bytes) is not int or type(max_entry_bytes) is not int
                or not 0 < max_entry_bytes <= max_bytes or max_entries < 1
                or not 1 <= consumers <= 64 or timeout < 0):
            raise ValueError('invalid shared data cache budget')
        self.base = Path(root)
        self.base.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = self.base / scope.key
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.max_bytes, self.max_entry_bytes = max_bytes, max_entry_bytes
        self.max_entries, self.consumers, self.timeout = max_entries, consumers, timeout
        policy = dict(max_bytes=max_bytes, max_entry_bytes=max_entry_bytes,
                      max_entries=max_entries, consumers=consumers)
        with _lock(self.base / 'policy.lock', timeout):
            policy_path = self.base / 'policy.json'
            if policy_path.exists() and json.loads(policy_path.read_text()) != policy:
                raise ValueError('processes sharing a cache root must use the same resource policy')
            policy_path.write_text(json.dumps(policy, sort_keys=True))

    @contextmanager
    def consumer(self, *, interactive=True, timeout=None):
        """Admission covers the whole request, including derived/JSON buffers."""
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            # Keep one slot available for web requests while batch jobs run.
            first = 0 if interactive or self.consumers == 1 else 1
            for index in range(first, self.consumers):
                manager = _lock(self.base / f'consumer-{index}.lock', 0)
                try:
                    manager.__enter__()
                except CacheBusy:
                    continue
                try:
                    yield
                finally:
                    manager.__exit__(None, None, None)
                return
            if time.monotonic() >= deadline:
                raise CacheBusy('shared data query concurrency budget exhausted')
            time.sleep(0.01)

    @staticmethod
    def _revision(path: Path):
        stat = path.stat()
        return (str(path.resolve()), stat.st_dev, stat.st_ino,
                stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    @contextmanager
    def borrow_chunk(self, chunk: str):
        """Lease an immutable published inode for native/cross-process readers.

        Pass a duplicated/transferred OS handle to the consumer, not a pathname
        which eviction can remove before it is opened. The caller must retain
        its normal query admission and must not write/truncate the file. A miss
        raises FileNotFoundError so the producer can be used again.
        """
        if (not isinstance(chunk, str) or len(chunk) != 64
                or any(c not in '0123456789abcdef' for c in chunk)):
            raise ValueError('expected published chunk identity')
        stripe = int(chunk[:8], 16) % 64
        with _lock(self.root / f'key-{stripe}.lock', self.timeout):
            path = self.root / f'{chunk}.arrow'
            handle = path.open('rb')
            try:
                os.utime(path, None)
            except BaseException:
                handle.close()
                raise
        try:
            yield handle
        finally:
            handle.close()

    def _reserve(self, stripe: int):
        reservation = self.root / f'{stripe}.reserve'
        with _lock(self.base / 'quota.lock', self.timeout):
            # Crash recovery uses the OS lock, not a PID or guessed timeout.
            for previous in self.base.glob('*/*.reserve'):
                other = int(previous.stem)
                if other == stripe and previous.parent == self.root:
                    previous.unlink(missing_ok=True)
                    for partial in self.root.glob(f'{other}.*.partial'):
                        partial.unlink(missing_ok=True)
                    continue
                try:
                    with _lock(previous.parent / f'key-{other}.lock', 0):
                        previous.unlink(missing_ok=True)
                        for partial in previous.parent.glob(f'{other}.*.partial'):
                            partial.unlink(missing_ok=True)
                except CacheBusy:
                    pass
            files = sorted(self.base.glob('*/*.arrow'), key=lambda p: p.stat().st_mtime_ns)
            reserved = sum(int(p.read_text()) for p in self.base.glob('*/*.reserve'))
            size = sum(p.stat().st_size for p in files)
            count = len(files) + len(list(self.base.glob("*/*.reserve")))
            for path in files:
                if size + reserved + self.max_entry_bytes <= self.max_bytes and count < self.max_entries:
                    break
                try:
                    other = int(path.stem[:8], 16) % 64
                    if other == stripe and path.parent == self.root:
                        removed = path.stat().st_size
                        path.unlink()
                    else:
                        with _lock(path.parent / f'key-{other}.lock', 0):
                            removed = path.stat().st_size
                            path.unlink()
                    size -= removed; count -= 1
                except (PermissionError, CacheBusy):  # pinned or opening entry
                    continue
            if size + reserved + self.max_entry_bytes > self.max_bytes or count >= self.max_entries:
                raise CacheLimit('shared data cache budget exhausted')
            reservation.write_text(str(self.max_entry_bytes))
        return reservation

    def iter_parquet_batches(self, path: str | Path, *, columns: Sequence[str],
                             row_groups: Sequence[int] | None = None, filters=(),
                             batch_size=4096, revision: str | None = None) -> Iterator:
        yield from self._iter_parquet(path, columns=columns, row_groups=row_groups,
            filters=filters, batch_size=batch_size, revision=revision)

    def iter_parquet_handles(self, path: str | Path, *, columns: Sequence[str] | None = None,
                             row_groups: Sequence[int] | None = None,
                             revision: str | None = None) -> Iterator:
        """Yield open immutable IPC files; duplicate before advancing iterator.

        Uses the same producer, cache keys and limits as Python batch readers.
        Cache hits do not decode Arrow batches in Python. The consumer owns row
        filtering and native event conversion, preserving exact timestamp units.
        """
        yield from self._iter_parquet(path, columns=columns, row_groups=row_groups,
                                     revision=revision, handles=True)

    def _iter_parquet(self, path: str | Path, *, columns: Sequence[str] | None,
                             row_groups: Sequence[int] | None = None, filters=(),
                             batch_size=4096, revision: str | None = None,
                             handles=False) -> Iterator:
        import pyarrow as pa
        import pyarrow.parquet as pq
        import pyarrow.compute as pc
        if batch_size < 1:
            raise ValueError('batch_size must be positive')
        path = Path(path).resolve(strict=True)
        before = self._revision(path)
        reader = pq.ParquetFile(path)
        columns = tuple(sorted(set(reader.schema_arrow.names if columns is None else columns)))
        groups = range(reader.metadata.num_row_groups) if row_groups is None else row_groups
        operators = {'>=': pc.greater_equal, '<=': pc.less_equal, '==': pc.equal}
        for column, operator, _ in filters:
            if column not in columns or operator not in operators:
                raise ValueError('invalid projected source filter')

        def selected(batch):
            for column, operator, value in filters:
                scalar = pa.scalar(value, type=batch.schema.field(column).type)
                batch = batch.filter(operators[operator](batch.column(column), scalar))
            return batch

        for group in groups:
            metadata = reader.metadata.row_group(group)
            indices = {metadata.column(i).path_in_schema: i for i in range(metadata.num_columns)}
            skip = False
            for column, operator, value in filters:
                stats = metadata.column(indices[column]).statistics if column in indices else None
                if stats is not None and stats.has_min_max and (
                    (operator == '>=' and stats.max < value)
                    or (operator == '<=' and stats.min > value)
                    or (operator == '==' and not stats.min <= value <= stats.max)
                ):
                    skip = True; break
            if skip:
                continue
            # Container bind mounts may expose one inode at different paths.
            # Scope + device/inode/revision identify that backing file; retain
            # the full path-based revision only for this reader's change checks.
            group_key = sha256(json.dumps([before[1:], revision, group, columns, CACHE_FORMAT_VERSION]).encode()).hexdigest()
            producer = None
            scanner, scanned = None, -1
            try:
                for chunk in range((metadata.num_rows + 4095) // 4096):
                    key = sha256(f'{group_key}:{chunk}'.encode()).hexdigest()
                    stripe = int(key[:8], 16) % 64
                    target = self.root / f'{key}.arrow'
                    # A producer holds only a source-group lock. Cached chunks
                    # remain immediately readable while the producer advances.
                    while True:
                        with _lock(self.root / f'key-{stripe}.lock', self.timeout):
                            if target.exists():
                                if handles:
                                    mapped = target.open('rb')
                                else:
                                    mapped = pa.memory_map(str(target), 'r')
                                    ipc = pa.ipc.open_file(mapped)
                                os.utime(target, None)
                                break
                        if producer is None:
                            producer = _lock(self.root / f'group-{int(group_key[:8],16)%64}.lock', self.timeout)
                            producer.__enter__()
                        with _lock(self.root / f'key-{stripe}.lock', self.timeout):
                            if target.exists():
                                continue
                            reservation = self._reserve(stripe)
                            fd, temporary = tempfile.mkstemp(prefix=f'{stripe}.{key}.', suffix='.partial', dir=self.root)
                            os.close(fd)
                            try:
                                if scanner is None:
                                    scanner = reader.iter_batches(row_groups=[group], columns=list(columns),
                                                                  batch_size=4096, use_threads=False)
                                while scanned < chunk:
                                    data = next(scanner)
                                    # Parquet projection can drop schema metadata (including
                                    # native event identities/precision). This changes only
                                    # the schema header, never copies the value buffers.
                                    data = data.replace_schema_metadata(reader.schema_arrow.metadata)
                                    scanned += 1
                                if data.nbytes > self.max_entry_bytes:
                                    raise CacheLimit('decoded batch exceeds cache entry budget')
                                with pa.OSFile(temporary, 'wb') as sink:
                                    with pa.ipc.new_file(sink, data.schema) as writer:
                                        writer.write_batch(data)
                                if Path(temporary).stat().st_size > self.max_entry_bytes:
                                    raise CacheLimit('IPC entry exceeds cache entry budget')
                                if self._revision(path) != before:
                                    raise RuntimeError('source changed during cache publication')
                                with _lock(self.base / 'quota.lock', self.timeout):
                                    os.replace(temporary, target)
                                    reservation.unlink(missing_ok=True)
                            finally:
                                Path(temporary).unlink(missing_ok=True)
                                with _lock(self.base / 'quota.lock', self.timeout):
                                    reservation.unlink(missing_ok=True)
                    try:
                        if handles:
                            yield mapped
                        else:
                            batch = ipc.get_batch(0)
                            for offset in range(0, batch.num_rows, batch_size):
                                yield selected(batch.slice(offset, batch_size))
                    finally:
                        mapped.close()
                    if self._revision(path) != before:
                        raise RuntimeError('source changed during data read')
            finally:
                if producer is not None:
                    producer.__exit__(None, None, None)


def host_input_cache(*, expected_role: str | None = None):
    """Host-local input cache; never a network cache or an authorization grant.

    Client applications must configure client role and explicit owner identity.
    Server web queries and local backtest preparation use the same host scope.
    """
    import socket
    role = os.environ.get("TR_DATA_HOST_ROLE", "server")
    if expected_role is not None and role != expected_role:
        raise ValueError("data host role does not match caller")
    owner = os.environ.get("TR_DATA_OWNER_REF", "platform" if role == "server" else "")
    scope = CacheScope(role, os.environ.get("FACTORTESTER_SERVER_ID") or socket.gethostname(),
                       owner, os.environ.get("TR_DATA_DEVICE_REF") or socket.gethostname())
    return _host_cache(str(Path(os.environ.get("TR_SHARED_DATA_CACHE_ROOT",
                       Path.home() / ".cache/traderesearch/columnar"))), scope,
                       int(os.environ.get("TR_SHARED_DATA_CACHE_BYTES", 512*1024**2)),
                       int(os.environ.get("TR_SHARED_DATA_ENTRY_BYTES", 64*1024**2)),
                       int(os.environ.get("TR_DATA_QUERY_CONCURRENCY", 4)))


from functools import lru_cache


@lru_cache(maxsize=8)
def _host_cache(root, scope, maximum, entry, consumers):
    return SharedColumnarCache(Path(root), scope, max_bytes=maximum,
                               max_entry_bytes=entry, consumers=consumers)


def batch_input_budget(function):
    """Host-local admission for batch preparation/replay, with a web slot reserved."""
    from functools import wraps
    @wraps(function)
    def run(*args, **kwargs):
        with host_input_cache().consumer(interactive=False, timeout=300):
            return function(*args, **kwargs)
    return run
