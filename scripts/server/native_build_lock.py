"""Serialize native builds sharing a Cargo target, without polling or new services."""
from __future__ import annotations
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    lock_path=Path(sys.argv[1]);lock_path.parent.mkdir(parents=True,exist_ok=True)
    with lock_path.open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('native build cache is in use; wait for the existing build',file=sys.stderr)
            return 75
        started=time.monotonic()
        result=subprocess.run(sys.argv[2:],env={**os.environ,'TR_NATIVE_BUILD_LOCK_HELD':'1'})
        print(f'native build exit={result.returncode} elapsed_seconds={time.monotonic()-started:.3f}',flush=True)
        return result.returncode

if __name__=='__main__':raise SystemExit(main())
