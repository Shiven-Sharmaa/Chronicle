"""Tier 2 attribution: `chronicle run --agent X -- <cmd>`.

While the wrapped child process is alive, the attribution resolver sees a
marker file for it and attributes every snapshot to that agent (confidence
'wrapper') -- unless a tier-1 hook claims it first. This is what makes
hook-less tools (Codex, or anything else with just a CLI) attributable at
all: "honest and simple," per the build plan, not a hook integration.
"""

from __future__ import annotations

import subprocess
import sys
import uuid

from chronicle import attribution
from chronicle.paths import Paths


def run(paths: Paths, agent: str, cmd: list[str]) -> int:
    if not cmd:
        print(
            "chronicle run: no command given (usage: chronicle run --agent X -- <cmd>)",
            file=sys.stderr,
        )
        return 2

    session_id = uuid.uuid4().hex
    proc = subprocess.Popen(cmd, cwd=paths.root)
    marker = attribution.register_wrapper(paths.chronicle_dir, proc.pid, agent, session_id)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.wait()
        return proc.returncode if proc.returncode is not None else 130
    finally:
        attribution.unregister_wrapper(marker)
