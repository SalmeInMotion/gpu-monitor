"""Finding app_template, the shared UI toolkit this card is built on.

Its path used to be hardcoded to Ivan's own machine in two places — the
entry point and the test suite — which made a clone unrunnable anywhere
else and, less obviously, made the two disagree the moment one was fixed.
One resolver, used by both.

Order is most-specific-first on purpose. The shared copy beats the
bundled one wherever it exists, so a fix to the template reaches this app
without re-vendoring; `vendor/` is what makes a fresh clone work on its
own.
"""

from __future__ import annotations

import os
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENV_VAR = "GPU_MONITOR_TEMPLATE"
SHARED_DIR = r"C:\IA\Tools\Windows\Template"
VENDOR_DIR = os.path.join(PROJECT_DIR, "vendor")


def candidates():
    return (os.environ.get(ENV_VAR), SHARED_DIR, VENDOR_DIR)


def find():
    """The first folder that actually contains an app_template package."""
    for candidate in candidates():
        if candidate and os.path.isdir(os.path.join(candidate, "app_template")):
            return candidate
    return None


def ensure_on_path():
    """Put the project and the template on sys.path. Returns the template
    folder used, and raises SystemExit with something actionable rather
    than letting `import app_template` fail three frames later."""
    if PROJECT_DIR not in sys.path:
        sys.path.insert(0, PROJECT_DIR)
    found = find()
    if found is None:
        raise SystemExit(
            "app_template not found. Set %s to the folder that contains "
            "it, or keep the bundled copy in %s." % (ENV_VAR, VENDOR_DIR))
    if found not in sys.path:
        sys.path.insert(0, found)
    return found
