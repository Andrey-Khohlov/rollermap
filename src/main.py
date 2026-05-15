from copy import deepcopy
from datetime import datetime, timedelta, date
from pathlib import Path
import sys
import logging
import json

from http.client import RemoteDisconnected
import urllib
import webbrowser
import folium
from folium.plugins import HeatMap, Draw
import gpxpy
import pandas as pd
from tabulate import tabulate

from config import (
    settings, 
    BoundingBox, 
    BASE_DIR, 
    TRACKS_DIR, 
    ZOOM_INITIAL, 
    HEATMAP_GRADIENT, 
    DECIMATION_FACTOR_YEAR, 
    DECIMATION_FACTOR_14, 
    ZOOM_MAX, 
    DAYS_14, 
    DRAW_OPTIONS, 
    EDIT_OPTIONS, 
    MO_BOX, 
    SVO_BOX
    )


logger = logging.getLogger(__name__)

_ASPHALT_DF = None  # cache

def get_asphalt_desc_data() -> pd.DataFrame:
    global _ASPHALT_DF

    if _ASPHALT_DF is not None:
        logger.debug("Используется кэш данных по состоянию асфальта")
        return _ASPHALT_DF

    logger.info("Загрузка данных состояния асфальта из внешнего источника")
    df = pd.DataFrame()
    try:
        df = pd.read_csv(settings.ASPHALT_URL)
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
    logger.debug("Удалено %s строк с непустым status", len(df) - len(df[df['status'].isna()]))
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
            "color": "red" if feature['properties'].get('action') == 'create'
                    else "green" if feature['properties'].get('action') == 'delete'
                    else "blue",      # на случай других значений
            "weight": 3,
            "opacity": 0.7,
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

def parse_gpx_points(gpx_path: str | Path, step: int, is_restriction: bool = False) -> list:
    """
    Парсит точки из GPX-файла (треки или ограничения).
    Для треков возвращает список [lat, lon]; для ограничений — список линий (каждая линия — список (lat, lon)).
    """
    with open(gpx_path, encoding="utf-8") as gpx_file:
        gpx = gpxpy.parse(gpx_file)

    if is_restriction:
        routes = [
            [(p.latitude, p.longitude) for p in route.points]
            for route in gpx.routes
        ]
        logger.debug("Ограничения из %s: %s маршрутов", gpx_path, len(routes))
        return routes

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
    logger.debug("Точки из %s: %s", gpx_path, len(points))
    return points

def get_tracks(period_days: int, step: int) -> list[tuple[float, float]]:
    """Собирает все точки треков за последние period_days дней."""
    logger.info("Сбор треков за %s дней (шаг прореживания: %s)", period_days, step)
    cutoff = (datetime.now() - timedelta(days=period_days)).timestamp()
    all_points: list[tuple[float, float]] = []
    files_processed = 0
    for track_file in Path(TRACKS_DIR).iterdir():
        if track_file.suffix.lower() != ".gpx":
            continue
        if track_file.stat().st_ctime > cutoff:
            all_points.extend(parse_gpx_points(track_file, step))
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
    logger.debug("Шаблон внедрен: %s", template_file)
   
def create_map(output_file: str | Path, title_file: str, period_days: int, step: int, zoom_max: int) -> None:
    """Создаёт карту с тепловым слоем треков."""
    logger.info("Создание карты: %s", output_file)

    all_points = get_tracks(period_days, step)
    center = (sum(p[0] for p in all_points) / len(all_points), sum(p[1] for p in all_points) / len(all_points))
    logger.debug("Центр карты рассчитан: lat=%.6f lon=%.6f", center[0], center[1])

    m = folium.Map(
        location=center,
        tiles="CartoDB Voyager",
        zoom_start=ZOOM_INITIAL,
        max_zoom=zoom_max,
    )

    HeatMap(
        all_points,
        max_zoom=16,
        radius=3,
        gradient=HEATMAP_GRADIENT,
        blur=1,
    ).add_to(m)

    asphalt_desc = insert_asphalt_desc()  # Добавляем слой плохого асфальта 
    if asphalt_desc:
        asphalt_desc.add_to(m)

    folium.plugins.LocateControl(keepCurrentZoomLevel=True).add_to(m)

    draw = Draw(export=False, draw_options=DRAW_OPTIONS, edit_options=EDIT_OPTIONS)  # export=False, т.к. мы сами отправляем данные
    draw.add_to(m)
    
    inject_template("draw_handler.js", m.get_root().html, {"{{GAS_URL}}": settings.GAS_URL})  # внедряем шаблон для сохранения рисунков в карту
    inject_template("buttons.html", m.get_root().html, {"__COMPILE_DATE__": datetime.now().strftime("%d.%m.%Y")})  # Вставляет кнопки «?» , «2 недели» , «2025» после <body>. Дату обновления.
    inject_template(title_file, m.get_root().header)  # Вставляет title & Analytics перед </head>.
    inject_template("add_to_drawn.js", m.get_root().html) 
 
    out_path = Path(output_file)
    m.save(str(out_path))
    attribution_removed = remove_attribution_line(out_path, target="attribution")  # удаляет подписи фреймворков с карты
    logger.debug("Постобработка attribution для %s: %s", out_path, attribution_removed)
    logger.info("Карта сохранена: %s", out_path)


def main() -> None:
    logger.info("Запуск генерации карт")

    map_configs = [
        (BASE_DIR / "index.html", "title.html", days_year_to_date(), DECIMATION_FACTOR_YEAR, ZOOM_MAX - 1),
        (BASE_DIR / "last_tracks.html", "title2.html", DAYS_14, DECIMATION_FACTOR_14, ZOOM_MAX),
    ]
    for output_path, title_file, period_days, step, zoom_max in map_configs:
        create_map(output_path, title_file=title_file, period_days=period_days, step=step, zoom_max=zoom_max)
    logger.info("Генерация карт завершена успешно")
    webbrowser.open(str(BASE_DIR / "index.html"))


if __name__ == "__main__":
    main()