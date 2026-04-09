import logging
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from datetime import date
from typing import NamedTuple


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---- Пути ----
BASE_DIR = Path(__file__).parent.parent
logger.debug(f'Looking for .env at: {BASE_DIR / ".env"}')
logger.debug(f'File exists: {(BASE_DIR / ".env").exists()}')
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
    SHEET_ID: str

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",  
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()