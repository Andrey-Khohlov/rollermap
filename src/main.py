from datetime import datetime, timedelta, date
import json
import os
from pathlib import Path
from typing import NamedTuple

import webbrowser
import logging

import folium
from folium.plugins import HeatMap
import gpxpy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths (BASE_DIR = project root)
_SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = _SCRIPT_DIR.parent
TRACKS_DIR = BASE_DIR / "tracks"
RESTRICTIONS_DIR = BASE_DIR / "tracks" / "restrictions"

# Map and track config
ZOOM_INITIAL = 12
ZOOM_MAX = 18
DAYS_14 = 14
YEAR_TO_DATE = (date.today() - date(date.today().year, 1, 1)).days
DECIMATION_FACTOR_YEAR = 4
DECIMATION_FACTOR_14 = 1


class BoundingBox(NamedTuple):
    lat_min: float  # South
    lat_max: float  # North
    lon_min: float  # East
    lon_max: float  # West


MO_BOX = BoundingBox(54.15, 56.788189, 35.08, 40.11)  # мск область, включая Конаково-Дубна
SVO_BOX = BoundingBox(55.959774, 55.984672, 37.372363, 37.453691)  # аэропорт Шереметьево


def in_box(lat: float, lon: float, box: BoundingBox) -> bool:
    return box.lat_min < lat < box.lat_max and box.lon_min < lon < box.lon_max


def transform_to_geojson(input_data: list) -> tuple:
    """
    Преобразует данные из формата JSON в формат GeoJSON.
    Возвращает список словарей:
    асфальт планируемый к ремонту, новый асфальт, плохой асфальт.
    """

    # Новый асфальт по global_id data.mos.ru работы начаты
    new_asphalt_ids = [
        2721481373, 2722035600, 2722025415, 2721217470, 1132362475, 2722035611, 2757253622, 2721220029,
                       2722035035, 2790280670, 2790280670, 2790280650,2783496038, 2790280623, 2755675840
                       ]

    # Плохой асфальт по global_id data.mos.ru
    destroyed_asphalt_ids = {
        # 2721958914: 'бордюринг 28.07.2025',
        # 2724150160: 'бордюринг 28.07.2025',
        # 2722037941: 'бордюринг 28.07.2025',
        # 2790280623: 'бордюринг 28.07.2025',
        # 2783496038: 'бордюринг 29.07.2025',
        # 2790280650: 'бордюринг 29.07.2025',
        # 2722221944: 'бордюринг 07.07, 31.07',
        # 2722081144: 'бордюринг 02.08',
        # 2721615482: 'бордюринг, четная сторона домов проезжаема 02.08',
        # 2722221945: 'бордюринг 16.08.2025',
        # 2721220076: 'бордюринг 16.08.2025',
        # 2721477917: 'снят асфальт, 17.08',
        # 2721486659: 'снят асфальт, 17.08',
        # 2721814959: 'снят асфальт, 17.08',
        # 2722035137: 'снят асфальт 22.08, 24.07',
    }

    new_asphalt = []
    destroyed_asphalt = []
    under_recon_asphalt = []

    for item in input_data:
        feature = {
            "type": "Feature",
            "geometry": {
                "type": item["Cells"]["geoData"]["type"],
                "coordinates": item["Cells"]["geoData"]["coordinates"]
            },
            "properties": {
                "datasetId": None,  # Можно заменить на нужное значение
                "rowId": None,  # Можно заменить на нужное значение
                "attributes": {
                    "is_deleted": 0,
                    "WorksPlace": item["Cells"]["WorksPlace"],
                    "WorkYear": item["Cells"]["WorkYear"],
                    "OnTerritoryOfMoscow": item["Cells"]["OnTerritoryOfMoscow"],
                    "AdmArea": item["Cells"]["AdmArea"],
                    "District": item["Cells"]["District"],
                    "WorksBeginDate": item["Cells"]["WorksBeginDate"],
                    "PlannedEndDate": item["Cells"]["PlannedEndDate"],
                    "ActualBeginDate": item["Cells"]["ActualBeginDate"],
                    "ActualEndDate": item["Cells"]["ActualEndDate"],
                    "WorksType": item["Cells"]["WorksType"],
                    "WorksStatus": item["Cells"]["WorksStatus"],
                    "WorkReason": item["Cells"]["WorkReason"],
                    "Customer": item["Cells"]["Customer"],
                    "Contractor": item["Cells"]["Contractor"],
                    "global_id": item["global_id"]
                },
                "display_name":  None,
            }
        }
        if item["global_id"] in new_asphalt_ids:
            new_asphalt.append(feature)
        elif item["global_id"] in destroyed_asphalt_ids:
            feature["properties"]["display_name"] = destroyed_asphalt_ids[item["global_id"]]
            destroyed_asphalt.append(feature)
        else:
            under_recon_asphalt.append(feature)

    return {"features": under_recon_asphalt}, {"features": new_asphalt}, {"features": destroyed_asphalt}


def _point_in_bounds(lat: float, lon: float) -> bool:
    """Точка в МО и не в зоне Шереметьево."""
    return in_box(lat, lon, MO_BOX) and not in_box(lat, lon, SVO_BOX)


def parse_gpx_points(gpx_path: str | Path, step: int, is_restriction: bool = False) -> list:
    """
    Парсит точки из GPX-файла (треки или ограничения).
    Для треков возвращает список [lat, lon]; для ограничений — список линий (каждая линия — список (lat, lon)).
    """
    with open(gpx_path, encoding="utf-8") as gpx_file:
        gpx = gpxpy.parse(gpx_file)

    if is_restriction:
        return [
            [(p.latitude, p.longitude) for p in route.points]
            for route in gpx.routes
        ]

    points: list[tuple[float, float]] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for i, point in enumerate(segment.points):
                if i % step == 0 and _point_in_bounds(point.latitude, point.longitude):
                    points.append((point.latitude, point.longitude))
    if not points and gpx.routes:
        for route in gpx.routes:
            for i, point in enumerate(route.points):
                if i % step == 0 and _point_in_bounds(point.latitude, point.longitude):
                    points.append((point.latitude, point.longitude))
    return points


def get_tracks(period_days: int, step: int) -> list[tuple[float, float]]:
    """Собирает все точки треков за последние period_days дней."""
    cutoff = (datetime.now() - timedelta(days=period_days)).timestamp()
    all_points: list[tuple[float, float]] = []
    for track_file in Path(TRACKS_DIR).iterdir():
        if track_file.suffix.lower() != ".gpx":
            continue
        if track_file.stat().st_ctime > cutoff:
            all_points.extend(parse_gpx_points(track_file, step))
    if not all_points:
        raise ValueError("Не найдено треков для построения карты!")
    return all_points


def _inject_html_snippet(html_path: Path, marker: str, snippet_path: Path, after: bool = True) -> None:
    """Вставляет содержимое snippet_path в html_path: после marker если after=True, иначе перед."""
    content = html_path.read_text(encoding="utf-8")
    snippet = snippet_path.read_text(encoding="utf-8")
    if after:
        new_content = content.replace(marker, marker + snippet)
    else:
        new_content = content.replace(marker, snippet + marker)
    html_path.write_text(new_content, encoding="utf-8")


def add_google_analytics(html_path: Path) -> None:
    """Вставляет Google Analytics перед </head>."""
    _inject_html_snippet(html_path, "</head>", BASE_DIR / "templates" / "google_tag.html", after=False)


def add_title(html_path: Path) -> None:
    """Вставляет заголовок и описание после <head>."""
    _inject_html_snippet(html_path, "<head>", BASE_DIR / "templates" / "title.html", after=True)


def add_last_tracks_button(html_path: Path) -> None:
    """Вставляет кнопку «последние треки» после <body>."""
    _inject_html_snippet(html_path, "<body>", BASE_DIR / "templates" / "last_tracks_button.html", after=True)

def remove_attribution_line(file_path: str | Path, target: str = "attribution", encoding: str = "utf-8") -> bool:
    """
    Удаляет строки, содержащие target, из файла.
    Добавляет "attributionControl": false после строки с "preferCanvas": false,.
    """
    path = Path(file_path)
    if not path.is_file():
        logger.warning("Файл не найден: %s", path)
        return False
    try:
        lines = path.read_text(encoding=encoding).splitlines(keepends=True)
    except OSError as e:
        logger.warning("Ошибка при чтении файла: %s", e)
        return False
    new_lines = [line for line in lines if target not in line]
    if len(new_lines) == len(lines):
        logger.warning("Строка с attribution не найдена. Файл не изменён.")
    out: list[str] = []
    prefer_found = False
    for line in new_lines:
        out.append(line)
        if "preferCanvas" in line:
            out.append('  "attributionControl": false, \n')
            prefer_found = True
    if not prefer_found:
        logger.warning('Строка с preferCanvas не найдена. "attributionControl": false не добавлен.')
    try:
        path.write_text("".join(out), encoding=encoding)
        return True
    except OSError as e:
        logger.warning("Ошибка при записи файла: %s", e)
        return False


HEATMAP_GRADIENT = {
    0.3: "purple",
    0.4: "blue",
    0.5: "cyan",
    0.9: "Yellow",
    1.0: "red",
}


def create_combined_map(output_file: str | Path, period_days: int, step: int) -> None:
    """Создаёт карту с тепловым слоем треков."""
    all_points = get_tracks(period_days, step)
    n = len(all_points)
    center = (sum(p[0] for p in all_points) / n, sum(p[1] for p in all_points) / n)

    m = folium.Map(
        location=center,
        tiles="CartoDB Voyager",
        zoom_start=ZOOM_INITIAL,
        max_zoom=ZOOM_MAX,
    )
    HeatMap(
        all_points,
        max_zoom=10,
        radius=4,
        gradient=HEATMAP_GRADIENT,
        blur=1,
    ).add_to(m)
    folium.plugins.LocateControl(keepCurrentZoomLevel=True).add_to(m)

    out_path = Path(output_file)
    m.save(str(out_path))
    logger.info("Карта сохранена: %s", out_path)


def _postprocess_html(html_path: Path) -> None:
    """Добавляет аналитику, заголовок, кнопку и убирает attribution."""
    add_google_analytics(html_path)
    add_title(html_path)
    add_last_tracks_button(html_path)
    remove_attribution_line(html_path, target="attribution")


def main() -> None:
    map_configs = [
        (BASE_DIR / "index.html", YEAR_TO_DATE, DECIMATION_FACTOR_YEAR),
        (BASE_DIR / "last_tracks.html", DAYS_14, DECIMATION_FACTOR_14),
    ]
    for output_path, period_days, step in map_configs:
        create_combined_map(output_path, period_days=period_days, step=step)
        _postprocess_html(output_path)
    webbrowser.open(str(BASE_DIR / "index.html"))


if __name__ == "__main__":
    main()