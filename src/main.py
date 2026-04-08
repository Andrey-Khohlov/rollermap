from datetime import datetime, timedelta, date
from io import BytesIO
from pathlib import Path
import re
from typing import NamedTuple
import logging
import json

from http.client import RemoteDisconnected
import urllib
import webbrowser
import folium
from folium.plugins import HeatMap, Draw
import gpxpy
import pandas as pd

from config import DRAW_OPTIONS, EDIT_OPTIONS, MO_BOX, SVO_BOX, logger, BoundingBox, settings, BASE_DIR, TRACKS_DIR, ZOOM_INITIAL, HEATMAP_GRADIENT, days_year_to_date, DECIMATION_FACTOR_YEAR, DECIMATION_FACTOR_14, ZOOM_MAX, DAYS_14


logger = logging.getLogger(__name__)

_BAD_ASPHALT_DF = None  # cache

def get_bad_asphalt_data() -> pd.DataFrame:
    global _BAD_ASPHALT_DF
    url = f"https://docs.google.com/spreadsheets/d/{settings.SHEET_ID}/export?format=csv"

    if _BAD_ASPHALT_DF is not None:
        return _BAD_ASPHALT_DF

    try:
        df = pd.read_csv(url)
        logger.info("Данные плохого асфальта успешно загружены из Google Sheets")
        _BAD_ASPHALT_DF = df
    except urllib.error.URLError as e:
        logger.error(f"Сетевая ошибка при чтении файла плохого асфальта из Google Sheets: {e}")
        _BAD_ASPHALT_DF = pd.DataFrame()
    except pd.errors.EmptyDataError:
        logger.warning("Файл CSV с геоданными плохого асфальта пуст")
        _BAD_ASPHALT_DF = pd.DataFrame()
    except RemoteDisconnected:
        logger.error("http.client.RemoteDisconnected: Remote end closed connection without response")
        raise
    except Exception as e:
        logger.error("Непредвиденная ошибка при загрузке файла плохого асфальта из Google Sheets")
        raise

    # если есть дубликаты поля GeoJSON, то рисовать только последнюю запись Series. 
    _BAD_ASPHALT_DF.drop_duplicates(subset='GeoJSON', keep='last', inplace=True)

    return _BAD_ASPHALT_DF

def _in_box(lat: float, lon: float, box: BoundingBox) -> bool:
    """Точка в bounding box."""
    return box.lat_min < lat < box.lat_max and box.lon_min < lon < box.lon_max


def _point_in_bounds(lat: float, lon: float) -> bool:
    """Точка в МО и не в зоне Шереметьево."""
    return _in_box(lat, lon, MO_BOX) and not _in_box(lat, lon, SVO_BOX)


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

def inject_template(template_file: str, target: folium.Element, replacements=None) -> None:
    """Чтение файла шаблона, опциональная замена подстановок и добавление сгенерированного элемента в объект folium.
        template_path - файла шаблон, 
        target - объект folium, 
        replacements - объекты подстановки.
    """
    template_path = BASE_DIR / "templates" / template_file
    js_code = template_path.read_text(encoding="utf-8")
    if replacements:
        for placeholder, value in replacements.items():
            js_code = js_code.replace(placeholder, value)
    target.add_child(folium.Element(js_code))

def insert_bad_asphalt() -> folium.GeoJson:

    df = get_bad_asphalt_data()
    if df.empty:
        return
    features = []
    for _, row in df.iterrows():
        try:
            geojson_dict = json.loads(row['GeoJSON'])
            date_obj = pd.to_datetime(row['Timestamp'], dayfirst=True)
            formatted_date = date_obj.strftime('%d-%b')  # '15-Mar'
            user_name = row['UserName']
            description = row['description']
            action = row['action']  
            prefix = 'Achtung! ' if action == 'create' else 'Починили! '
            bold_prefix = f"<b>{prefix}</b>" 
            popup_html = f"{bold_prefix}{formatted_date}\n{user_name}: \n{description}"
            feature = {
                "type": "Feature",
                "geometry": geojson_dict["geometry"],
                "properties": {
                    "popup": popup_html,
                    "action": action  
                }
            }
            features.append(feature)
        except Exception as e:
            print(f"Ошибка при обработке строки: {e}. Пропускаем.")
            continue
    
    geojson_layer = folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        # Стиль линии – теперь цвет выбирается динамически
        style_function=lambda feature: {
            "color": "red" if feature['properties'].get('action') == 'create'
                    else "lightgreen" if feature['properties'].get('action') == 'delete'
                    else "blue",      # на случай других значений
            "weight": 3,
            "opacity": 0.7,
        },
        # Всплывающая подсказка при наведении
        tooltip=folium.GeoJsonTooltip(
            fields=['popup'],
            aliases=[""],
            localize=True,
            sticky=False,
            labels=True,
            style="""
                background-color: #F0F0F0;
                border: 1px solid black;
                border-radius: 3px;
                box-shadow: 3px;
                font-size: 12px;
            """,
        ),
        # Всплывающее окно при клике
        popup=folium.GeoJsonPopup(fields=['popup'], aliases=['Детали:'], localize=True),
    )
    return geojson_layer
    


def create_map(output_file: str | Path, period_days: int, step: int, zoom_max: int) -> None:
    """Создаёт карту с тепловым слоем треков."""

    all_points = get_tracks(period_days, step)
    center = (sum(p[0] for p in all_points) / len(all_points), sum(p[1] for p in all_points) / len(all_points))

    m = folium.Map(
        location=center,
        tiles="CartoDB Voyager",
        zoom_start=ZOOM_INITIAL,
        max_zoom=zoom_max,
    )

    HeatMap(
        all_points,
        max_zoom=10,
        radius=4,
        gradient=HEATMAP_GRADIENT,
        blur=1,
    ).add_to(m)

    bad_asphalt = insert_bad_asphalt()  # Добавляем слой плохого асфальта 
    if bad_asphalt:
        bad_asphalt.add_to(m)

    folium.plugins.LocateControl(keepCurrentZoomLevel=True).add_to(m)

    draw = Draw(export=False, draw_options=DRAW_OPTIONS, edit_options=EDIT_OPTIONS)  # export=False, т.к. мы сами отправляем данные
    draw.add_to(m)
    
    inject_template("draw_handler.js", m.get_root().html, {"{{GAS_URL}}": settings.GAS_URL})  # внедряем шаблон для сохранения рисунков в карту
    inject_template("last_tracks_button.html", m.get_root().html)  # Вставляет кнопку «последние треки» после <body>.
    inject_template("title.html", m.get_root().header)  # Вставляет title & Analytics перед </head>.
 
    out_path = Path(output_file)
    m.save(str(out_path))
    remove_attribution_line(out_path, target="attribution")  # удаляет подписи фреймворков с карты
    logger.info("Карта сохранена: %s", out_path)


def main() -> None:
    map_configs = [
        (BASE_DIR / "index.html", days_year_to_date(), DECIMATION_FACTOR_YEAR, ZOOM_MAX),
        (BASE_DIR / "last_tracks.html", DAYS_14, DECIMATION_FACTOR_14, ZOOM_MAX),
    ]
    for output_path, period_days, step, zoom_max in map_configs:
        create_map(output_path, period_days=period_days, step=step, zoom_max=zoom_max)
    webbrowser.open(str(BASE_DIR / "index.html"))


if __name__ == "__main__":
    main()