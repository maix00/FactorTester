from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_artifact_client_retries_webkit_load_failed_after_reissuing_access():
    source = ROOT / "server" / "manager" / "web" / "jobs" / "artifacts.js"
    program = f"""
global.window = globalThis;
window.location = {{origin: "https://manager.example"}};
window.crypto = {{randomUUID: () => "test-request"}};
window.FTJobArtifacts = undefined;
eval(require("fs").readFileSync({json.dumps(str(source))}, "utf8"));
let accessAttempts = 0;
let dataAttempts = 0;
global.fetch = async () => {{
  dataAttempts += 1;
  if (dataAttempts < 3) throw new TypeError("Load failed");
  return {{ok: true, status: 200}};
}};
(async () => {{
  const context = {{
    api: async () => {{
      accessAttempts += 1;
      return {{access: {{url: "https://storage.example/data", bearer: "ticket"}}}};
    }},
    t: value => value,
  }};
  await FTJobArtifacts.fetch(context, "/api/artifact");
  console.log(JSON.stringify({{accessAttempts, dataAttempts}}));
}})().catch(error => {{
  console.error(error);
  process.exit(1);
}});
"""
    result = subprocess.run(
        ["node", "-e", program],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {"accessAttempts": 3, "dataAttempts": 3}
