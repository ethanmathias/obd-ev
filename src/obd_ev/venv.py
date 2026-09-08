"""Hand execution to the project virtualenv.

`bleak` and `mpu6050-raspberrypi` are pip-installed into `.venv`, not
system-wide. A script run as `./scripts/sensors.py` therefore starts on the
system interpreter and reports them missing -- which reads as broken hardware
rather than the wrong interpreter, and is exactly the kind of misleading
signal a diagnostic tool must not produce.

Scripts that need those packages call `reexec_if_needed()` before importing
anything that depends on them.
"""

import os
import sys
from pathlib import Path

_GUARD = "OBD_EV_NO_REEXEC"


def venv_python() -> Path:
    return Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"


def reexec_if_needed() -> None:
    """Replace this process with the venv interpreter, if there is one and we
    are not already running under it. A no-op otherwise, so the scripts still
    work from a system install or an activated environment."""
    if os.environ.get(_GUARD):
        return
    target = venv_python()
    try:
        if not target.exists():
            return
        if Path(sys.executable).resolve() == target.resolve():
            return
    except OSError:
        return

    # Guard against an exec loop if the venv interpreter somehow resolves
    # elsewhere; one hop is all this should ever need.
    os.environ[_GUARD] = "1"
    script = os.path.abspath(sys.argv[0])
    os.execv(str(target), [str(target), script, *sys.argv[1:]])
