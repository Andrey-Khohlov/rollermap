from copy import deepcopy
from datetime import datetime, timedelta, date
import math
import os
from pathlib import Path
import sys
import logging
import json

from http.client import RemoteDisconnected
from typing import List
import urllib
import webbrowser
import folium
from folium.plugins import HeatMap, Draw
import gpxpy
import pandas as pd
from tabulate import tabulate
from tqdm import tqdm
from shapely.geometry import LineString

from config import (
    settings, 
    BoundingBox, 
    DEV_MODE, 
    BASE_DIR, 
    TRACKS_DIR, 
    ZOOM_INITIAL, 
    HEATMAP_GRADIENT, 
    MIN_DISTANCE_METERS_YEAR, 
    MIN_DISTANCE_METERS_14, 
    ZOOM_MAX, 
    DAYS_14, 
    DRAW_OPTIONS, 
    EDIT_OPTIONS, 
    MO_BOX, 
    SVO_BOX
    )


logger = logging.getLogger(__name__)

_ASPHALT_DF = None  # cache

def export_df(df):
    df_filtered = df.copy()
    features = []
    for idx, row in df_filtered.iterrows():
        # TODO добавить отсечку по дате raw['Timestamp']
        geojson_str = row['GeoJSON']
        if pd.isna(geojson_str):
            continue
        
        try:
            feature = json.loads(geojson_str) 
        except json.JSONDecodeError:
            print(f"Ошибка парсинга GeoJSON в строке {idx}")
            continue
        
        if 'properties' not in feature or feature['properties'] is None:
            feature['properties'] = {}
        
        feature['properties']['description'] = str(row['description'] if isinstance(row['description'], str) else '')
        if not isinstance(row['Timestamp'], str):
            row['Timestamp'] = str(row['Timestamp'])
        dt = datetime.strptime(row['Timestamp'], '%d.%m.%Y %H:%M:%S')
        feature['properties']['description'] += ' (' + dt.strftime("%d.%m.%y") + ')'
        if row['UserName'] != 'Аноним':
            feature['properties']['description']  += ' - ' + row['UserName']
        if row['action'] == 'delete':
            feature['properties']['stroke'] = "#56db40" # light green
        elif row['action'] == 'create':
            feature['properties']['stroke'] = "#ff931e" # orange
            # "#1bad03" - red
        else:
            logger.exception("Неожиданный аргумент в поле row['action']: %s", row['action'])
            raise
        
        features.append(feature)

    feature_collection = {
        "type": "FeatureCollection",
        "features": features
    }

    output_file = "output/asphalt.geojson"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(feature_collection, f, ensure_ascii=False, indent=2)
    
    logger.info("Экспорт раскопок успешно завершен. Сохранено %s объектов в %s", len(features), output_file)


def get_asphalt_desc_data() -> pd.DataFrame:
    global _ASPHALT_DF

    if _ASPHALT_DF is not None:
        logger.debug("Используется кэш данных по состоянию асфальта")
        return _ASPHALT_DF

    logger.info("Загрузка данных состояния асфальта из внешнего источника")
    df = pd.DataFrame()
    try:
        df = pd.read_csv(settings.ASPHALT_URL, engine='python')
        logger.info("Данные по состоянию асфальта успешно загружены: %s записей", len(df))
    except urllib.error.URLError as e:
        logger.error("Сетевая ошибка при чтении файла состояния асфальта: %s", e)
        sys.exit(1)
    except pd.errors.EmptyDataError:
        logger.error("Файл с состоянием асфальта пуст")
        sys.exit(1)
    except RemoteDisconnected:
        logger.error("Удаленная сторона разорвала соединение при загрузке асфальта")
        sys.exit(1)
    except Exception as e:
        logger.exception("Непредвиденная ошибка при загрузке файла плохого асфальта")
        raise
    # Удаляем строки с непустым status (оставляем только пустые)
    df = df[df['status'].isna()]
    logger.info("Удалено %s строк с непустым status", len(df) - len(df[df['status'].isna()]))
    logger.debug(tabulate(df, headers="keys", tablefmt="psql"))
    _ASPHALT_DF = deepcopy(df)
    if not df.empty:
        #  проверка delete of deleted item - потребует ручного разбора
        df['geometry_data'] = df['GeoJSON'].apply(lambda x: json.loads(x).get('geometry').get('coordinates'))
        df['geometry_data'] = df['geometry_data'].apply(json.dumps)
        df.drop(columns='GeoJSON', inplace=True)
        df_filtered = df[df.groupby('geometry_data')['action'].transform(lambda x: x.duplicated().any())]
        col_to_move = ['description', 'geometry_data']
        cols = [col for col in df_filtered.columns if col not in col_to_move] + col_to_move
        df_filtered = df_filtered[cols]
        if not df_filtered.empty:
            table = tabulate(df_filtered, headers="keys", tablefmt="psql")
            logger.warning("Есть попытки удаления уже удаленных элементов:\n" + table)
        # если есть дубликаты поля GeoJSON, то рисовать только последнюю запись. 
        before_dedup = len(_ASPHALT_DF)
        _ASPHALT_DF.drop_duplicates(subset='GeoJSON', keep='last', inplace=True)
        logger.info(
            "Данные асфальта подготовлены: %s -> %s записей после удаления дубликатов",
            before_dedup,
            len(_ASPHALT_DF),
        )
    table = tabulate(_ASPHALT_DF, headers="keys", tablefmt="psql")
    logger.info("_ASPHALT_DF:\n%s", table)
    export_df(_ASPHALT_DF)

    return _ASPHALT_DF

def insert_asphalt_desc() -> folium.GeoJson:

    df = get_asphalt_desc_data()
    if df.empty:
        logger.info("Слой состояния асфальта не добавлен: нет данных")
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
                    "popup_min": f"{bold_prefix}{formatted_date}\n{user_name}",
                    "action": action
                }
            }
            features.append(feature)
        except Exception as e:
            logger.warning("Ошибка при обработке строки: %s. Пропускаем.", e)
            continue
    logger.info("Подготовлено %s geojson-объектов состояния асфальта", len(features))
    
    geojson_layer = folium.GeoJson(
        {"type": "FeatureCollection", "features": features},
        overlay=True,
        style_function=lambda feature: {
            "color": "magenta" if feature['properties'].get('action') == 'create'
                    else "lime" if feature['properties'].get('action') == 'delete'
                    else "blue",      # на случай других значений
            "weight": 3,
            "opacity": 1,
        },
        # Всплывающая подсказка при наведении
        tooltip=folium.GeoJsonTooltip(
            fields=['popup_min'],
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
        popup=folium.GeoJsonPopup(fields=['popup'], aliases=[''], localize=True),
    )
    return geojson_layer

def days_year_to_date() -> int:
    today = date.today()
    return (today - date(today.year, 1, 1)).days

def _in_box(lat: float, lon: float, box: BoundingBox) -> bool:
    """Точка в bounding box."""
    return box.lat_min < lat < box.lat_max and box.lon_min < lon < box.lon_max

def _point_in_bounds(lat: float, lon: float) -> bool:
    """Точка в МО и не в зоне Шереметьево."""
    return _in_box(lat, lon, MO_BOX) and not _in_box(lat, lon, SVO_BOX)

def haversine(lat1, lon1, lat2, lon2):
    """Расстояние между двумя точками на сфере в метрах (формула гаверсинуса)."""
    R = 6371000  # радиус Земли, м
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def filter_points_by_distance(points_iter, min_distance_meters):
    """
    Прореживание последовательности точек: сохраняются только те,
    что находятся на расстоянии >= min_distance_meters от последней сохранённой.
    Каждый новый вызов начинает с пустого состояния.
    """
    result = []
    last_lat = last_lon = None
    for point in points_iter:
        if not _point_in_bounds(point.latitude, point.longitude):
            continue
        if last_lat is None:
            # всегда берём первую подходящую точку
            result.append((point.latitude, point.longitude))
            last_lat, last_lon = point.latitude, point.longitude
        else:
            dist = haversine(last_lat, last_lon, point.latitude, point.longitude)
            if dist >= min_distance_meters:
                result.append((point.latitude, point.longitude))
                last_lat, last_lon = point.latitude, point.longitude
    return result

def extract_points(gpx_path: str | Path):
    """
    Извлекает точки из GPX-объекта с пространственным прореживанием.
    Параметры:
      gpx — объект, содержащий tracks и routes (например, из gpxpy)
      min_distance_meters — минимальное расстояние между сохраняемыми точками (м)
      gpx_path — путь к файлу (для логирования)
    """
    with open(gpx_path, encoding="utf-8") as gpx_file:
        gpx = gpxpy.parse(gpx_file)

    points = []

    for track in gpx.tracks:
        for segment in track.segments:
            points.extend(segment.points)

    if not points and gpx.routes:
        for route in gpx.routes:
            points.extend(route.points)

    return points

def get_tracks(period_days: int, min_distance_meters: int) -> list[tuple[float, float]]:
    """Собирает все точки треков за последние period_days дней."""
    # logger.info("Сбор треков за %s дней (шаг прореживания: %s)", period_days, step)
    logger.info("Сбор треков за %s дней", period_days)
    cutoff = (datetime.now() - timedelta(days=period_days)).timestamp()
    all_points: list[tuple[float, float]] = []
    files_processed = 0
    total = sum(1 for _ in Path(TRACKS_DIR).iterdir())
    for track_file in tqdm(list(Path(TRACKS_DIR).iterdir())[:], total=total, desc="Обработка треков"):  
        if track_file.suffix.lower() != ".gpx":
            continue
        if DEV_MODE and track_file.stat().st_ctime  < (datetime.now() - timedelta(days=2)).timestamp():   # Сократить обработку треков в режиме разработки
            continue
        if track_file.stat().st_ctime < cutoff:
            continue
        points = extract_points(gpx_path=track_file)
        points = filter_points_by_distance(points, min_distance_meters)
        all_points.extend(points)
        files_processed += 1
    if not all_points:
        logger.error("Не найдено треков для построения карты (период: %s дней)", period_days)
        raise ValueError("Не найдено треков для построения карты!")
    logger.info("Собрано %s точек из %s GPX-файлов", "{:,}".format(len(all_points)), files_processed)
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

def inject_template(template_file: str, target: folium.Element, replacements: dict = None) -> None:
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
    logger.debug("Шаблон внедрен: %s", template_file)

def create_map_general(
    output_file: str | Path,
    title_file: str,
    layer: folium.Element,          # готовый слой (HeatMap, PolyLine и т.п.)
    zoom_max: int = 18,
    center: tuple[float, float] | None = None,
    ) -> None:
    """Создаёт карту с произвольным слоем на основе переданных точек."""
    logger.info("Создание карты: %s", output_file)

    if center is None:
        center = (55.752936, 37.623021)

    m = folium.Map(
        location=center,
        crs="EPSG3395",
        tiles=f"https://tiles.api-maps.yandex.ru/v1/tiles/?x={{x}}&y={{y}}&z={{z}}&lang=ru_RU&l=map&apikey={settings.YANDEX_API_KEY}",
        attr="Яндекс.Карты",
        zoom_start=ZOOM_INITIAL,
        max_zoom=zoom_max,
        min_zoom=9,
        min_lat=54,
        max_lat=57,
        min_lon=34,
        max_lon=41,
    )

    layer.add_to(m)

    asphalt_desc = insert_asphalt_desc()
    if asphalt_desc:
        asphalt_desc.add_to(m)

    folium.plugins.LocateControl(keepCurrentZoomLevel=True).add_to(m)
    folium.plugins.Fullscreen().add_to(m)

    draw = Draw(export=False, draw_options=DRAW_OPTIONS, edit_options=EDIT_OPTIONS)
    draw.add_to(m)

    inject_template("draw_handler.js", m.get_root().html, {"{{GAS_URL}}": settings.GAS_URL})
    inject_template("buttons.html", m.get_root().html, {
        "__COMPILE_DATE__": datetime.now().strftime("%d.%m.%Y"),
        "{{GPX_UPLOADER_APP_URL}}": settings.GPX_UPLOADER_APP_URL,
    })
    inject_template(title_file, m.get_root().header)
    inject_template("add_to_drawn.js", m.get_root().html)
    m.get_root().html.add_child(folium.JavascriptLink('https://cdnjs.cloudflare.com/ajax/libs/leaflet-gpx/1.7.0/gpx.min.js'))
    inject_template("yandex_logo.html", m.get_root().html)

    out_path = Path(output_file)
    m.save(str(out_path))
    logger.info("Карта сохранена: %s", out_path)
    attribution_removed = remove_attribution_line(out_path, target="attribution")
    logger.debug("Постобработка attribution для %s: %s", out_path, attribution_removed)

def split_lines_by_gap(coords, threshold) -> List[List]:
    """
    Разбивает список координат на несколько,
    если расстояние между соседними точками превышает threshold в метрах.
    
    :param coords: список кортежей (долгота, широта)
    :param threshold_km: порог в километрах
    :return: список полилиний
    """
    if len(coords) < 2:
        return [coords]  # вырожденный случай

    lines = []
    start_idx = 0  # индекс начала текущей линии

    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        dist = haversine(lat1, lon1, lat2, lon2)

        if dist > threshold:
            # Разрыв: заканчиваем текущую линию на точке i
            segment = coords[start_idx:i + 1]
            if len(segment) >= 2:
                lines.append(segment)
            # Новая линия начинается со следующей точки
            start_idx = i + 1

    # Последний сегмент (от start_idx до конца)
    last_segment = coords[start_idx:]
    if len(last_segment) >= 2:
        lines.append(last_segment)

    return lines

def create_polyline_map(
    output_file: str | Path,
    title_file: str,
    period_days: int,
    points: list[tuple[float, float]],
    zoom_max: int = 18,
    ) -> None:
    """Создаёт карту с линиями по трекам."""
    cutoff = (datetime.now() - timedelta(days=period_days)).timestamp()
    total = sum(1 for _ in Path(TRACKS_DIR).iterdir())
    simplified_tracks = []
    files_processed = 0
    for track_file in tqdm(list(Path(TRACKS_DIR).iterdir())[:], total=total, desc="Обработка треков"):  
        if track_file.suffix.lower() != ".gpx":
            continue
        if DEV_MODE and track_file.stat().st_ctime  < (datetime.now() - timedelta(days=2)).timestamp():   # Сократить обработку треков в режиме разработки
            continue
        if track_file.stat().st_ctime < cutoff:
            continue
        gpx_points = extract_points(track_file)  # это список объектов GPXPoint
        if not gpx_points:
            continue
        coords = [(p.longitude, p.latitude) for p in gpx_points]  # список объектов GPXPoint в формат (долгота, широта) для Shapely
        for coords_ in split_lines_by_gap(coords, 12):
            original_line = LineString(coords_)
            simplified_line = original_line.simplify(tolerance=0.0001, preserve_topology=False)
            # Преобразуем обратно в (широта, долгота) для Folium
            # simplified.coords возвращает (lon, lat)
            points_lat_lon = [(lat, lon) for lon, lat in simplified_line.coords]
            simplified_tracks.append(points_lat_lon)
        files_processed += 1
    
    if not simplified_tracks:
        logger.exception("Нет треков для отображения")
        raise

    all_points = [p for pts in simplified_tracks for p in pts]
    center = (sum(p[0] for p in all_points) / len(all_points),
              sum(p[1] for p in all_points) / len(all_points))

    # Создаём слой (FeatureGroup) для всех линий
    layer = folium.FeatureGroup(name="Tracks simplified")

    for points in simplified_tracks:
        # Добавляем каждую линию как отдельный PolyLine с именем файла
        folium.PolyLine(
            points,
            color="blue",
            weight=0.7,
            opacity=0.5,
            smoothFactor=1.0,  # помогает при зуме
        ).add_to(layer)
    logger.info("Собрано %s точек из %s GPX-файлов", "{:,}".format(len(all_points)), files_processed)
    create_map_general(output_file, title_file, layer, zoom_max, center=center)
    
def create_map(
    output_file: str | Path,
    title_file: str,
    period_days: int,
    min_distance_meters: int,
    zoom_max: int,
) -> None:
    """Создаёт карту с тепловым слоем (для обратной совместимости)."""
    points = get_tracks(period_days, min_distance_meters)
    heat_layer = HeatMap(
        points,
        name="Heatmap_Tracks",
        min_opacity=0.2,
        max_zoom=14,
        radius=5,
        gradient=HEATMAP_GRADIENT,
        blur=1,
    )
    center = (sum(p[0] for p in points) / len(points),
                  sum(p[1] for p in points) / len(points))
    logger.debug("Центр карты рассчитан: lat=%.6f lon=%.6f", center[0], center[1])
    create_map_general(output_file, title_file, heat_layer, zoom_max, center)
       
# def create_map(output_file: str | Path, title_file: str, period_days: int, min_distance_meters: int, zoom_max: int) -> None:
#     """Создаёт карту с тепловым слоем треков."""
#     logger.info("Создание карты: %s", output_file)

#     all_points = get_tracks(period_days, min_distance_meters)
#     center = (sum(p[0] for p in all_points) / len(all_points), sum(p[1] for p in all_points) / len(all_points))
#     logger.debug("Центр карты рассчитан: lat=%.6f lon=%.6f", center[0], center[1])

#     m = folium.Map(
#         location=center,
#         crs="EPSG3395",
#         tiles=f"https://tiles.api-maps.yandex.ru/v1/tiles/?x={{x}}&y={{y}}&z={{z}}&lang=ru_RU&l=map&apikey={settings.YANDEX_API_KEY}",
#         attr="Яндекс.Карты",
#         zoom_start=ZOOM_INITIAL,
#         max_zoom=zoom_max,
#         min_zoom=9,
#         min_lat=54,
#         max_lat=57,
#         min_lon=34,
#         max_lon=41,
#     )
    
#     HeatMap(
#         all_points,
#         name="Heatmap_Tracks",
#         min_opacity=0.2,
#         max_zoom=14,
#         radius=9,
#         gradient=HEATMAP_GRADIENT,
#         blur=1,
#     ).add_to(m)

#     asphalt_desc = insert_asphalt_desc()  # Добавляем слой плохого асфальта 
#     if asphalt_desc:
#         asphalt_desc.add_to(m)

#     folium.plugins.LocateControl(keepCurrentZoomLevel=True).add_to(m)
#     folium.plugins.Fullscreen().add_to(m)

#     draw = Draw(export=False, draw_options=DRAW_OPTIONS, edit_options=EDIT_OPTIONS)  # export=False, т.к. мы сами отправляем данные
#     draw.add_to(m)
    
#     inject_template("draw_handler.js", m.get_root().html, {"{{GAS_URL}}": settings.GAS_URL})  # внедряем шаблон для сохранения рисунков в карту
#     # Вставляет кнопки «?» , «2 недели» , «2025» после <body>. Дату обновления.
#     inject_template("buttons.html", m.get_root().html, {"__COMPILE_DATE__": datetime.now().strftime("%d.%m.%Y"), "{{GPX_UPLOADER_APP_URL}}": settings.GPX_UPLOADER_APP_URL})  
#     inject_template(title_file, m.get_root().header)  # Вставляет title & Analytics перед </head>.
#     inject_template("add_to_drawn.js", m.get_root().html)  # для включения режима редактирования для всех уже загруженных GeoJSON-данных на карте
#     m.get_root().html.add_child(folium.JavascriptLink('https://cdnjs.cloudflare.com/ajax/libs/leaflet-gpx/1.7.0/gpx.min.js'))  # используется для загрузки gpx
#     inject_template("yandex_logo.html", m.get_root().html)  # Добавляет лого Яндекса
 
#     out_path = Path(output_file)
#     m.save(str(out_path))
#     logger.info("Карта сохранена: %s", out_path)
#     attribution_removed = remove_attribution_line(out_path, target="attribution")  # удаляет подписи фреймворков с карты
#     logger.debug("Постобработка attribution для %s: %s", out_path, attribution_removed)
    
    
def write_sitemap(output_path: str, template_path: str = "sitemap_template.xml") -> None:
    """
    Генерирует sitemap, подставляя сегодняшнюю дату в шаблон,
    и записывает результат в файл.
    """
    bike_file = "bike-hitting/index.html" 
    mtime = os.path.getmtime(bike_file)
    bike_date = datetime.fromtimestamp(mtime).date().isoformat()

    with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()
    today = date.today().isoformat()
    content = template.replace("[today]", today) 
    content = content.replace("[bike-mtime]", bike_date)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

def main() -> None:
    logger.info("Запуск генерации карт в режиме разработки: %s", DEV_MODE)

    map_configs = [
        (BASE_DIR / "index.html", "title.html", days_year_to_date(), MIN_DISTANCE_METERS_YEAR, ZOOM_MAX - 1),
        (BASE_DIR / "last_tracks.html", "title2.html", DAYS_14, MIN_DISTANCE_METERS_14, ZOOM_MAX),
    ]
    for output_path, title_file, period_days, min_distance_meters, zoom_max in map_configs:
        create_map(output_path, title_file=title_file, period_days=period_days, min_distance_meters=min_distance_meters, zoom_max=zoom_max)
    # create_map(BASE_DIR / "index.html", "title.html", days_year_to_date(), MIN_DISTANCE_METERS_YEAR, ZOOM_MAX - 1)
    create_polyline_map(BASE_DIR / "lines.html", "title2.html", days_year_to_date(), MIN_DISTANCE_METERS_14, ZOOM_MAX)
    logger.info("Генерация карт завершена успешно")
    webbrowser.open(str(BASE_DIR / "index.html"))

    write_sitemap(output_path=BASE_DIR / "sitemap.xml", template_path=BASE_DIR / "templates" / "template_sitemap.xml")
    logger.info("Генерация sitemap.html завершена.")


if __name__ == "__main__":
    main()