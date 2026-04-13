import logging
import sys
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import NamedTuple

# ---- Пути ----
BASE_DIR = Path(__file__).parent.parent
TRACKS_DIR = BASE_DIR / "tracks"
RESTRICTIONS_DIR = BASE_DIR / "tracks" / "restrictions"

# ---- Настройки карты ----
ZOOM_INITIAL = 12
ZOOM_MAX = 17  # максимальное увеличение карты
DAYS_14 = 14  # дней отображения  для карты последних треков

DECIMATION_FACTOR_YEAR = 4  # прореживание для уменьшения размера карты 2026
DECIMATION_FACTOR_14 = 2  # прореживание для уменьшения размера карты 2 нед

HEATMAP_GRADIENT = {
    0.3: "purple",
    0.4: "blue",
    0.5: "cyan",
    0.9: "yellow", 
    1.0: "red",
}

# ---- Настройки плагина Draw (панель рисования) ----
DRAW_OPTIONS = {
    "polyline": True,   
    "polygon": False,   
    "rectangle": False, 
    "circle": False,    
    "marker": False,    
    "circlemarker": False 
}
EDIT_OPTIONS = {
    "edit": False,  
    "remove": True    
}

# ---- Гео-ограничения ----
class BoundingBox(NamedTuple):
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

MO_BOX = BoundingBox(54.15, 56.788189, 35.08, 40.11)
SVO_BOX = BoundingBox(55.959774, 55.984672, 37.372363, 37.453691)


class Settings(BaseSettings):
    GAS_URL: str
    ASPHALT_URL: str
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",  
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


def _resolve_log_level(raw_level: str) -> int:
    """Convert LOG_LEVEL from env to logging level."""
    level = getattr(logging, raw_level.upper(), None)
    if isinstance(level, int):
        return level
    return logging.INFO


def configure_logging() -> None:
    """Configure root logger once for the whole application."""
    logging.basicConfig(
        level=_resolve_log_level(settings.LOG_LEVEL),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
        force=True,
    )