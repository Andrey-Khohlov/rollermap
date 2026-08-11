import logging
import sys
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from typing import NamedTuple


logging.basicConfig(level = logging.INFO,
                    format= "[%(levelname)s] [%(name)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stderr)]
                    )                    
logger = logging.getLogger(__name__)


DEV_MODE = True

# ---- Пути ----
BASE_DIR = Path(__file__).parent.parent
TRACKS_DIR = BASE_DIR / "tracks"
RESTRICTIONS_DIR = BASE_DIR / "tracks" / "restrictions"
logger.debug(f'Looking for .env at: {BASE_DIR / ".env"}')
logger.debug(f'File exists: {(BASE_DIR / ".env").exists()}')

# ---- Настройки карты ----
ZOOM_INITIAL = 11
ZOOM_MAX = 18  # максимальное увеличение карты
DAYS_14 = 14  # дней отображения  для карты последних треков

MIN_DISTANCE_METERS_YEAR = 80  # минимальное расстояние между точками в метрах для карты 2026
MIN_DISTANCE_METERS_14 = 20  # минимальное расстояние между точками в метрах для карты 2 нед

HEATMAP_GRADIENT = {
    0.3: "purple",
    0.45: "blue",
    0.6: "cyan",
    0.75: "yellow", 
    0.85: "red",
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
    GPX_FOLDER: str
    GPX_UPLOADER_APP_URL: str
    YANDEX_API_KEY: str

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",  
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

