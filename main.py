import json
import os

import webbrowser
import gpxpy
import folium
import requests
from dotenv import load_dotenv
from folium.plugins import HeatMap
from numpy.distutils.misc_util import yellow_text


def transform_to_geojson(input_data):
    '''
    Преобразует данные из формата JSON в формат GeoJSON и возвращает список словарей:
    асфальт плани руемый к ремонту, новый асфальт, плохой асфальт.
    '''
    new_asphalt_ids = [2721481373, 2722035600, 2722025415, ]
    destroyed_asphalt_ids = [2722221944, 2722221945, 2721220076]
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
                "releaseNumber": 2,  # Можно заменить на нужное значение
                "versionNumber": 3  # Можно заменить на нужное значение
            }
        }
        if item["global_id"] in new_asphalt_ids:
            new_asphalt.append(feature)
        elif item["global_id"] in destroyed_asphalt_ids:
            destroyed_asphalt.append(feature)
        else:
            under_recon_asphalt.append(feature)

    return {"features": under_recon_asphalt}, {"features": new_asphalt}, {"features": destroyed_asphalt}

def parse_gpx_points(gpx_path, is_restriction=False):
    """Парсит точки из GPX-файла (треки или ограничения)"""
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
        return points


def create_mosres_json():
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

def create_combined_map(tracks_dir, restrictions_dir, output_file="index.html"):
    """Создает карту с тепловым слоем и ограничениями"""
    # 1. Собираем все точки треков
    all_points = []
    for track_file in os.listdir(tracks_dir):
        if track_file.lower().endswith('.gpx'):
            track_path = os.path.join(tracks_dir, track_file)
            all_points.extend(parse_gpx_points(track_path))

    if not all_points:
        raise ValueError("Не найдено треков для построения карты!")

    # 2. Собираем все ограничения созданные вручную
    all_restrictions = []
    all_restrictions_names = []
    for restriction_file in os.listdir(restrictions_dir):
        if restriction_file.endswith('.gpx'):
            restriction_path = os.path.join(restrictions_dir, restriction_file)
            all_restrictions.extend(parse_gpx_points(restriction_path, is_restriction=True))
            all_restrictions_names.append(restriction_file.split('.')[0].split()[0])

    # 3. Создаем карту
    avg_lat = sum(p[0] for p in all_points) / len(all_points)
    avg_lon = sum(p[1] for p in all_points) / len(all_points)
    m = folium.Map(location=[avg_lat, avg_lon], tiles="CartoDB Voyager", zoom_start=12)

    # 5. Добавляем ограничения data.mos.ru
    if 'mos_res.json' not in os.listdir():
        restrictions = create_mosres_json()
    else:
        with open('mos_res.json', 'r') as f:
            restrictions = json.load(f)
    restrictions = transform_to_geojson(restrictions)
    folium.GeoJson(restrictions[0]).add_to(m)
    folium.GeoJson(restrictions[1], color='green', weight=3).add_to(m)
    folium.GeoJson(restrictions[2], color='red', weight=3, opaqcity=0.75).add_to(m)

    # 4. Тепловая карта
    yell = 'yellow'
    HeatMap(
        all_points,
        max_zoom=8,
        radius=3,
        # gradient={0.4: 'blue', 0.9: yell, 1: 'red'},
        blur=2
    ).add_to(m)

    """
    # 6. Ограничения соранные вручную (разные цвета для разных файлов)
    colors = ['darkred', 'purple', 'orange']  # Цвета для разных файлов
    for i, restriction in enumerate(all_restrictions):
        folium.PolyLine(
            restriction,
            color=colors[i % len(colors)],
            weight=4,
            opacity=0.8,
            dash_array='10, 5',
            tooltip=f"Ограничение {all_restrictions_names[i]}"
        ).add_to(m)

    # 7. Легенда с динамическим списком ограничений
    legend_html = f'''
    <div style="position: fixed; 
                bottom: 20px; left: 20px; 
                width: 200px;
                background: white; 
                border: 2px solid grey;
                padding: 10px;
                font-size: 14px;
                z-index: 1000;">
        <b>Легенда</b><br>
        <span style="background: linear-gradient(to right, blue, lime, red);
                    display: inline-block; 
                    width: 100%; height: 20px;
                    margin-bottom: 5px;"></span>
        Интенсивность движения<br>

    for i in range(len(all_restrictions)):
        legend_html += f'''
        <span style="color: {colors[i % len(colors)]}; font-weight: bold;">
        — — —</span> Ограничение {all_restrictions_names[i]}<br>

    legend_html += '</div>'
    # отрисовка легенды
    # m.get_root().html.add_child(folium.Element(legend_html))
    """

    # 8. Контроль местоположения
    folium.plugins.LocateControl().add_to(m)

    # 9. Сохраняем карту
    m.save(output_file)
    print(f"Карта сохранена в файл: {output_file}")
    return m



if __name__ == "__main__":
    # пути к папкам
    TRACKS_DIR = "./tracks"  # Папка с GPX-файлами треков
    RESTRICTIONS_DIR = "./tracks/restrictions"  # Папка с файлами ограничений

    # Создаем карту
    create_combined_map(TRACKS_DIR, RESTRICTIONS_DIR)

    # Открытие в браузере
    webbrowser.open('index.html')