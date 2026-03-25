from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"CSV não encontrado: {path}")
    logger.info("Lendo CSV: %s", path)
    return pd.read_csv(path)
