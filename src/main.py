from datetime import datetime, timedelta, date
import json
import os
from pathlib import Path
import sys
from typing import NamedTuple
import webbrowser
import logging

import requests

from dotenv import load_dotenv
import folium
from folium.plugins import HeatMap
import gpxpy
import pyproj

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()



BASE_DIR = "/home/xgb/projects/rollermap"  # пути к папкам
TRACKS_DIR = os.path.join(BASE_DIR, "tracks")  # Папка с GPX-файлами треков
RESTRICTIONS_DIR = os.path.join(BASE_DIR, "tracks", "restrictions")  # Папка с файлами ограничений
ZOOM_INITIAL= 12  # открытие карты на этом зуме
ZOOM_MAX: int  = 18  # максимальное увеличение карты, влияет на производительность
DAYS_14: int  = 14
YEAR_TO_DATE: int  = (date.today() - date(date.today().year, 1, 1)).days  # дней с начала года
DECIMATION_FACTOR_YEAR: int = 4  # прореживаем треки на карте года
DECIMATION_FACTOR_14: int = 1  # прореживаем треки на карте 2 недели


class BoundingBox(NamedTuple):
    lat_min: float  # South
    lat_max: float  # North
    lon_min: float  # East
    lon_max: float  # West


MO_BOX = BoundingBox(54.15, 56.788189, 35.08, 40.11)  # мск область, включая Конаково-Дубна
SVO_BOX = BoundingBox(55.959774, 55.984672, 37.372363, 37.453691)  # аэропорт Шереметьево


def in_box(lat: float, lon: float, box: BoundingBox) -> bool:
    return box.lat_min < lat < box.lat_max and box.lon_min < lon < box.lon_max
    
def transform_to_geojson(input_data):
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

def parse_gpx_points(gpx_path, step, is_restriction=False) -> list:
    """
    Парсит точки из GPX-файла (треки или ограничения)
    Возвращает список точек в формате [широта, долгота]
    """

    with open(gpx_path, 'r') as gpx_file:
        gpx = gpxpy.parse(gpx_file)

    if is_restriction:
        # Для файлов ограничений (маршруты/routes)
        lines = []
        for route in gpx.routes:
            line = [(point.latitude, point.longitude) for point in route.points]
            lines.append(line)
        return lines
    else:
        # Для обычных треков
        points = []
        for track in gpx.tracks:
            for segment in track.segments:
                for i, point in enumerate(segment.points):
                    if i % step == 0 and in_box(point.latitude, point.longitude, MO_BOX) and not in_box(point.latitude, point.longitude, SVO_BOX):
                        points.append((point.latitude, point.longitude))
        if not points:
            for route in gpx.routes:
                for point in enumerate(route.points):
                    if i % step == 0 and in_box(point.latitude, point.longitude, MO_BOX) and not in_box(point.latitude, point.longitude, SVO_BOX):
                        points.append([point.latitude, point.longitude])
        return points

def get_tracks(period_days, step) -> list:
    """Собираем все точки треков"""

    period_days_ago_timestamp = (datetime.now()- timedelta(days=period_days)).timestamp()
    all_points = []
    for track_file in Path(TRACKS_DIR).iterdir():
        if track_file.name.lower().endswith('.gpx'):
            creation_time = track_file.stat().st_ctime
            if creation_time > period_days_ago_timestamp:
                all_points.extend(parse_gpx_points(track_file, step))
    if not all_points:
        raise ValueError("Не найдено треков для построения карты!")

    return all_points

def add_google_analytics():
    """Добавляем Google Analytics"""

    # Читаем index.html
    with open(BASE_DIR + "/index.html", "r", encoding="utf-8") as file:
        content = file.read()
    # Код для вставки
    with open(BASE_DIR + '/templates/google_tag.html', "r", encoding="utf-8") as file:
        analytics_code = file.read()
    # Вставляем перед закрывающим </head>
    new_content = content.replace("</head>", analytics_code + "</head>")
    # Записываем обратно
    with open(BASE_DIR + "/index.html", "w", encoding="utf-8") as file:
        file.write(new_content)

def add_title():
    """Добавляем заголовок и описание сайта"""

    # Читаем index.html
    with open(BASE_DIR + "/index.html", "r", encoding="utf-8") as file:
        content = file.read()
    # Код для вставки
    with open(BASE_DIR + '/templates/title.html', "r", encoding="utf-8") as file:
        title = file.read()
    # Вставляем после открывающим <head>
    new_content = content.replace("<head>", "<head>" + title)
    # Записываем обратно
    with open(BASE_DIR + "/index.html", "w", encoding="utf-8") as file:
        file.write(new_content)

def add_last_tracks_button(html_file):
    """добавляем кнопку из файла last_tracks_button.html"""
    # Читаем html_file (index.html)
    with open(html_file, "r", encoding="utf-8") as file:
        content = file.read()
    # Код для вставки
    with open(BASE_DIR + '/templates/last_tracks_button.html', "r", encoding="utf-8") as file:
        title = file.read()
    # Вставляем после открывающего <body>
    new_content = content.replace("<body>", "<body>" + title)
    # Записываем обратно
    with open(html_file, "w", encoding="utf-8") as file:
        file.write(new_content)

def remove_attribution_line(file_path, target="attribution", encoding='utf-8'):
    """
    Удаляет строки, содержащие target, из указанного файла.
    Добавляет строку 
      "attributionControl": false 
    после строки
      "preferCanvas": false,
    """
    # Проверяем, существует ли файл
    if not os.path.isfile(file_path):
        logger.warning(f"Ошибка: файл '{file_path}' не найден.", file=sys.stderr)
        return False
    # Читаем все строки
    try:
        with open(file_path, 'r', encoding=encoding) as f:
            lines = f.readlines()
    except Exception as e:
        logger.warning(f"Ошибка при чтении файла: {e}", file=sys.stderr)
        return False
    # Фильтруем строки
    new_lines = [line for line in lines if target not in line]  
    if len(new_lines) == len(lines):  # Если ничего не изменилось, сообщаем об этом
        logger.warning("Строка с attribution не найдена. Файл не изменён.")

    new_lines_2 = []
    for line in new_lines:
        new_lines_2.append(line)
        if "preferCanvas" in line:
            new_lines_2.append('  "attributionControl": false, ')
    if len(new_lines_2) == len(new_lines):  # Если ничего не изменилось, сообщаем об этом
        logger.warning('Строка с preferCanvas не найдена. "attributionControl": false не добавлен.')     
    # Записываем изменения обратно в файл
    try:
        with open(file_path, 'w', encoding=encoding) as f:
            f.writelines(new_lines_2)
        logger.debug(f"Удалено {len(lines) - len(new_lines)} строк(а). Файл обновлён.")
        logger.debug(f"Добавлено {len(new_lines_2) - len(new_lines)} строк(а). Файл обновлён.")
        return True
    except Exception as e:
        logger.warning(f"Ошибка при записи файла: {e}", file=sys.stderr)
        return False


def create_combined_map(output_file, period_days, step):
    """Создает карту с тепловым слоем и ограничениями"""

    # 1. Собираем все точки
    all_points = get_tracks(period_days, step)

    # 2. Создаем карту
    avg_lat = sum(p[0] for p in all_points) / len(all_points)
    avg_lon = sum(p[1] for p in all_points) / len(all_points)
    # tiles_yandex = 'https://core-renderer-tiles.maps.yandex.net/tiles?l=map&x={x}&y={y}&z={z}'
    # m = folium.Map(location=[avg_lat, avg_lon], tiles=tiles_yandex, attr='Яндекс.Карты', zoom_start=12, max_zoom=16)
    # + нужен оффсет для карты Яндекса
    m = folium.Map(location=[avg_lat, avg_lon], tiles="CartoDB Voyager", zoom_start=ZOOM_INITIAL, max_zoom=ZOOM_MAX)

    # add_gov_restrictions(m)
    # add_manual_restrictions(m)

    # 5. Добавляем тепловую карту
    custom_gradient = {
        0.3: 'purple',
        0.4: 'blue',
        0.5: 'cyan',
        # 0.65: 'lime',
        0.9: 'Yellow',
        # 0.95: 'orange',
        1.0: 'red'
    }
    HeatMap(
        all_points,
        max_zoom=10,
        radius=4,
        gradient=custom_gradient,
        blur=1
    ).add_to(m)

    # 6. Добавляем легенду
    # add_legend(m)

    # 7. Добавляем контроль местоположения
    folium.plugins.LocateControl(keepCurrentZoomLevel=True).add_to(m)

    # 8. Сохраняем карту
    m.save(output_file)
    logger.info(f"Карта сохранена в файл: {output_file}")


def main():

    create_combined_map(output_file=BASE_DIR + "/index.html", period_days=YEAR_TO_DATE, step=DECIMATION_FACTOR_YEAR)
    add_google_analytics()
    add_title()
    add_last_tracks_button(BASE_DIR + "/index.html",)
    remove_attribution_line(BASE_DIR + "/index.html", target="attribution")

    create_combined_map(output_file="last_tracks.html", period_days=DAYS_14, step=DECIMATION_FACTOR_14)
    add_google_analytics()
    add_title()
    add_last_tracks_button(BASE_DIR + "/last_tracks.html")
    remove_attribution_line(BASE_DIR + "/last_tracks.html", target="attribution")

    webbrowser.open(BASE_DIR + '/index.html')

if __name__ == "__main__":
    main()