"""
    Configuration loader for the multi-store scraper.
    Reads from config.yaml in the project root if available;
    otherwise falls back to built-in defaults.
"""

import logging
from pathlib import Path
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: Dict[str, Any] = {
    "stores": {
        "amazon": {
            "base_url": "https://www.amazon.com",
        },
        # Future stores:
        # "cruz_verde": {"base_url": "https://www.cruzverde.com.co"},
        # "farmatodo": {"base_url": "https://www.farmatodo.com"},
        # "locatel": {"base_url": "https://www.locatel.com.co"},
        # "colsubsidio": {"base_url": "https://www.colsubsidio.com"},
    },
    "categories": {
        "baby": {
            "keywords": [
                "pañal",
                "pañales",
                "fórmula",
                "formula",
                "biberón",
                "biberon",
                "toallitas",
                "crema bebé",
                "crema bebe",
                "shampoo bebé",
                "shampu bebe",
                "papilla",
                "gerber",
                "nan",
                "promod",
                "enfagrow",
                "similac",
                "continente",
                "cereal",
                "mamadera",
                "chupón",
                "chupon",
                "cobertor",
                "pañalera",
                "humidificador",
                "termómetro",
                "jarabe bebé",
                "vitamina bebé",
            ]
        },
    },
    "output_dir": "output",
}


def load_config(config_path: str | None = None) -> Dict[str, Any]:
    """
    Load configuration from a YAML file, falling back to defaults.

    Args:
        config_path: Path to a config.yaml file. If None, looks for
                     config.yaml in the current directory and then in
                     the project root.

    Returns:
        Merged configuration dict.
    """
    config = DEFAULT_CONFIG.copy()

    search_paths = []
    if config_path:
        search_paths.append(Path(config_path))
    search_paths.append(Path.cwd() / "config.yaml")
    search_paths.append(Path(__file__).resolve().parent.parent.parent / "config.yaml")

    for path in search_paths:
        if path.exists():
            logger.info(f"Loading config from {path}")
            with open(path, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f) or {}
            # Shallow merge top-level keys
            for key, value in user_config.items():
                if (
                    key in config
                    and isinstance(config[key], dict)
                    and isinstance(value, dict)
                ):
                    config[key].update(value)
                else:
                    config[key] = value
            break
    else:
        logger.info("No config.yaml found. Using default configuration.")

    return config
