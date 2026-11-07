"""Keep the browser demo's configuration in step with the backend.

The demo (frontend/src/demo/) runs without a backend, so it carries a copy of
the default configuration in default-config.json and serves it from its mock
``GET /api/config``. If the configuration model changes, the copy must change
with it, or the demo shows settings the real service doesn't have.
"""

import json
from pathlib import Path

from app.config.config_manager import AutoHealConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_DEFAULT_CONFIG = REPO_ROOT / "frontend" / "src" / "demo" / "default-config.json"


def test_demo_default_config_matches_the_backend_defaults():
    demo = json.loads(DEMO_DEFAULT_CONFIG.read_text(encoding="utf-8"))
    # Regenerate with: AutoHealConfig().model_dump(mode="json"), indent 2.
    assert demo == AutoHealConfig().model_dump(mode="json")
