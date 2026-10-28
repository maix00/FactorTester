from pathlib import Path
import os
import subprocess
import sys
import time

SCRIPT=Path(__file__).resolve().parents[2]/'scripts/server/native_build_lock.py'

def test_shared_cache_builds_are_serialized_and_unlock_on_failure(tmp_path):
    lock=tmp_path/'lock';ready=tmp_path/'ready'
    command=[sys.executable,str(SCRIPT),str(lock),sys.executable,'-c']
    first=subprocess.Popen(command+[f"from pathlib import Path;import time;Path({str(ready)!r}).touch();time.sleep(1);raise SystemExit(4)"],stdout=subprocess.PIPE,text=True)
    try:
        deadline=time.monotonic()+5
        while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
        assert ready.exists()
        blocked=subprocess.run(command+['raise SystemExit(0)'],capture_output=True,text=True)
        assert blocked.returncode==75
        assert first.wait(timeout=5)==4
        success=subprocess.run(command+['import os;assert os.environ["TR_NATIVE_BUILD_LOCK_HELD"]=="1"'],capture_output=True,text=True)
        assert success.returncode==0,success.stderr
        assert 'elapsed_seconds=' in success.stdout
    finally:
        if first.poll() is None:first.terminate();first.wait(timeout=5)
