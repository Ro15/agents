import json
import logging
from pathlib import Path
from typing import List

from app.plugin_loader import PluginConfig, PluginDefinition

logger = logging.getLogger(__name__)


class PluginValidationError(Exception):
    pass


def validate_plugin(plugin_path: Path) -> PluginDefinition:
    """
    Strictly load and validate a plugin.
    Raises PluginValidationError with helpful detail on failure.
    """
    plugin_id = plugin_path.name
    try:
        cfg = PluginConfig(plugin_id, str(plugin_path.parent))
    except Exception as e:
        raise PluginValidationError(f"{plugin_id}: failed to load configs -> {e}") from e

    if not cfg.validated:
        raise PluginValidationError(f"{plugin_id}: validation errors -> {json.dumps(cfg.validation_errors)}")

    return cfg.to_definition()


def list_plugin_paths(plugins_root: Path) -> List[Path]:
    return [p for p in plugins_root.iterdir() if p.is_dir() and not p.name.startswith(".")]
