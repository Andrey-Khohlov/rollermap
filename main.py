from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import webbrowser
from datetime import date

import requests

from dotenv import load_dotenv
import folium
from folium.plugins import HeatMap
import gpxpy
import pyproj


ZOOM_INITIAL= 12  # открытие карты на этом зуме
ZOOM_MAX: int  = 18  # максимальное увеличение карты, вляет на производительность
DAYS_14: int  = 14
YEAR_TO_DATE: int  = (date.today() - date(date.today().year, 1, 1)).days # дней с начала года


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

def parse_gpx_points(gpx_path, is_restriction=False) -> list:
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
                for point in segment.points:
                    points.append([point.latitude, point.longitude])
        if not points:
            for route in gpx.routes:
                for point in route.points:
                    points.append([point.latitude, point.longitude])
        return points

def create_mos_res_json() -> dict:
    """
    Загружает JSON с ограничениями Москвы и сохраняет его в файл mos_res.json
    """

    load_dotenv()  # Загрузить переменные из .env
    api_key = os.getenv("api_key")  # Использовать секреты
    url = 'https://apidata.mos.ru/v1/datasets/62101/rows'
    params = {
        "$filter": "WorkYear eq 2025 and WorksStatus eq 'идут'",
        "api_key": api_key,
    }
    restrictions = None
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # Проверка на ошибки HTTP (4xx/5xx)
        # Обработка ответа
        if response.status_code == 200:
            restrictions = response.json()
            with open("mos_res.json", "w") as f:
                json.dump(restrictions, f)
            print("Успешный ответ dat.mos.ru")
        else:
            print("Ошибка:", response.status_code, response.text)
    except requests.exceptions.RequestException as e:
        print("Ошибка запроса:", e)
    return restrictions

def get_tracks(tracks_dir, period_days=365) -> list:
    """
    Собираем все точки треков
    """
    period_days_ago_timestamp = (datetime.now()- timedelta(days=period_days)).timestamp()
    all_points = []
    for track_file in Path(tracks_dir).iterdir():
        if track_file.name.lower().endswith('.gpx'):
            creation_time = track_file.stat().st_ctime
            if creation_time <= period_days_ago_timestamp:
                continue
            all_points.extend(parse_gpx_points(track_file))

    '''Исключаем выход за пределы мск области,крайние точки Московской области по широте и долготе:
    Север: 56°57    ', 37°42'. включить Конаково-Дубна: 56.788189, 36.832014
    Восток: 55°30    ', 40°11'.
    Юг: 54°15    ', 38°39'.
    Запад: 55°21    ', 35°08'.'''
    all_points = [p for p in all_points if 54.15 < p[0] < 56.788189 and 35.08 < p[1] < 40.11]
    ''' исключаем аэропорт Шереметьево
    Север: 55.984672, 37.431077
    Юг: 55.959774, 37.411990
    Запад: 55.968036, 37.372363
    Восток: 55.976297, 37.453691'''
    all_points = [p for p in all_points if any([p[0] > 55.984672, p[0] < 55.959774, p[1] < 37.372363, p[1] > 37.453691])]
    # прореживаем треки, оставляем только каждую n-ю точку
    all_points = all_points[::10 if period_days > 30 else 1]

    if not all_points:
        raise ValueError("Не найдено треков для построения карты!")
    return all_points

def add_google_analytics():
    """Добавляем Google Analytics"""

    # Читаем index.html
    with open("index.html", "r", encoding="utf-8") as file:
        content = file.read()
    # Код для вставки
    with open('google_tag.html', "r", encoding="utf-8") as file:
        analytics_code = file.read()
    # Вставляем перед закрывающим </head>
    new_content = content.replace("</head>", analytics_code + "</head>")
    # Записываем обратно
    with open("index.html", "w", encoding="utf-8") as file:
        file.write(new_content)

def add_title():
    """Добавляем заголовок и описание сайта"""

    # Читаем index.html
    with open("index.html", "r", encoding="utf-8") as file:
        content = file.read()
    # Код для вставки
    with open('title.html', "r", encoding="utf-8") as file:
        title = file.read()
    # Вставляем после открывающим <head>
    new_content = content.replace("<head>", "<head>" + title)
    # Записываем обратно
    with open("index.html", "w", encoding="utf-8") as file:
        file.write(new_content)

def add_last_tracks_button(html_file):
    """добавляем кнопку из файла last_tracks_button.html"""
    # Читаем html_file (index.html)
    with open(html_file, "r", encoding="utf-8") as file:
        content = file.read()
    # Код для вставки
    with open('last_tracks_button.html', "r", encoding="utf-8") as file:
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
        print(f"Ошибка: файл '{file_path}' не найден.", file=sys.stderr)
        return False

    # Читаем все строки
    try:
        with open(file_path, 'r', encoding=encoding) as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Ошибка при чтении файла: {e}", file=sys.stderr)
        return False

    # Фильтруем строки
    new_lines = [line for line in lines if target not in line]


    # Если ничего не изменилось, сообщаем об этом
    if len(new_lines) == len(lines):
        print("Строка с attribution не найдена. Файл не изменён.")
        # return True

    # Добавляет строку 
    new_lines_2 = []
    for line in new_lines:
        new_lines_2.append(line)
        if "preferCanvas" in line:
            new_lines_2.append('  "attributionControl": false, ')

    # Если ничего не изменилось, сообщаем об этом
    if len(new_lines_2) == len(new_lines):
        print('Строка с preferCanvas не найдена. "attributionControl": false не добавлен.')
        # return True       

    # Записываем изменения обратно в файл
    try:
        with open(file_path, 'w', encoding=encoding) as f:
            f.writelines(new_lines_2)
        print(f"Удалено {len(lines) - len(new_lines)} строк(а). Файл обновлён.")
        print(f"Добавлено {len(new_lines_2) - len(new_lines)} строк(а). Файл обновлён.")
        return True
    except Exception as e:
        print(f"Ошибка при записи файла: {e}", file=sys.stderr)
        return False


def create_combined_map(tracks_dir, restrictions_dir, output_file, period_days):
    """Создает карту с тепловым слоем и ограничениями"""

    # 1. Собираем все точки
    all_points = get_tracks(tracks_dir, period_days)


    # 2. Создаем карту
    avg_lat = sum(p[0] for p in all_points) / len(all_points)
    avg_lon = sum(p[1] for p in all_points) / len(all_points)
    # tiles_yandex = 'https://core-renderer-tiles.maps.yandex.net/tiles?l=map&x={x}&y={y}&z={z}'
    # m = folium.Map(location=[avg_lat, avg_lon], tiles=tiles_yandex, attr='Яндекс.Карты', zoom_start=12, max_zoom=16)
    # + нужен оффсет для карты Яндекса
    m = folium.Map(location=[avg_lat, avg_lon], tiles="CartoDB Voyager", zoom_start=ZOOM_INITIAL, max_zoom=ZOOM_MAX)

    # 3. Добавляем ограничения на карту
    # restrictions = None
    # if 'mos_res.json' not in os.listdir():
    #     restrictions = create_mos_res_json()
    # else:
    #     with open('mos_res.json', 'r') as f:
    #         restrictions = json.load(f)
    # restrictions = transform_to_geojson(restrictions)
    # 3.1 Планируемые работы по data.mos.ru
    # folium.GeoJson(restrictions[0]).add_to(m)
    # 3.2 Хороший асфальт
    # folium.GeoJson(restrictions[1], color='green', weight=3).add_to(m)
    # 3.3 Плохой асфальт на базе улиц data.mos.ru
    # get_tooltip = GeoJsonTooltip(
    #     fields=["display_name"],  # Поля из feature["properties"]
    #     aliases=[""],  # Подписи к полям
    #     localize=True,
    #     sticky=True
    # )
    # folium.GeoJson(restrictions[2], color='red', weight=3, opaqcity=0.75, tooltip=get_tooltip).add_to(m)

    # 4. Добавляем ограничения собранные вручную
    # add_manual_restrictions(m, restrictions_dir)

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
    print(f"Карта сохранена в файл: {output_file}")


def main():
    # пути к папкам
    BASE_DIR = "/home/xgb/projects/rollermap"
    TRACKS_DIR = os.path.join(BASE_DIR, "tracks")  # Папка с GPX-файлами треков
    RESTRICTIONS_DIR = os.path.join(BASE_DIR, "tracks", "restrictions")  # Папка с файлами ограничений

    create_combined_map(TRACKS_DIR, RESTRICTIONS_DIR, output_file="index.html", period_days=YEAR_TO_DATE)
    add_google_analytics()
    add_title()
    add_last_tracks_button("index.html")
    remove_attribution_line("index.html", target="attribution")

    create_combined_map(TRACKS_DIR, RESTRICTIONS_DIR, output_file="last_tracks.html", period_days=DAYS_14)
    add_google_analytics()
    add_title()
    add_last_tracks_button("last_tracks.html")
    remove_attribution_line("last_tracks.html", target="attribution")

    webbrowser.open('index.html')

if __name__ == "__main__":
    main()