import json
import os

import webbrowser
import gpxpy
import folium
import requests
from dotenv import load_dotenv
from folium import GeoJsonTooltip
from folium.plugins import HeatMap


def transform_to_geojson(input_data):
    """
    Преобразует данные из формата JSON в формат GeoJSON.
    Возвращает список словарей:
    асфальт планируемый к ремонту, новый асфальт, плохой асфальт.
    """

    # Новый асфальт по global_id data.mos.ru
    new_asphalt_ids = [2721481373, 2722035600, 2722025415, 2721217470]

    # Плохой асфальт по global_id data.mos.ru
    destroyed_asphalt_ids = {
        2722221944: 'бордюринг 07.07.2025',
        2722221945: 'бордюринг 07.07.2025',
        2721220076: 'бордюринг 07.07.2025',
        2721958914: 'бордюринг 28.07.2025',
        2724150160: 'бордюринг 28.07.2025',
        2722037941: 'бордюринг 28.07.2025',
        2790280623: 'бордюринг 28.07.2025',
        2783496038: 'бордюринг 29.07.2025',
        2790280650: 'бордюринг 29.07.2025',
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

def get_tracks(tracks_dir) -> list:
    """
    Собираем все точки треков
    """

    all_points = []
    for track_file in os.listdir(tracks_dir):
        if track_file.lower().endswith('.gpx'):
            track_path = os.path.join(tracks_dir, track_file)
            all_points.extend(parse_gpx_points(track_path))
    # прореживаем треки, оставляем только каждую n-ю точку
    all_points = all_points[::5]
    if not all_points:
        raise ValueError("Не найдено треков для построения карты!")
    return all_points

def add_legend(m) -> None:
    """Легенда с динамическим списком ограничений"""

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
        Интенсивность движения<br>'''
    for i in range(len(all_restrictions)):
        legend_html += f'''
        <span style="color: {colors[i % len(colors)]}; font-weight: bold;">
        — — —</span> Ограничение {all_restrictions_names[i]}<br>

    legend_html += '</div>'  '''
    # отрисовка легенды
    m.get_root().html.add_child(folium.Element(legend_html))

def add_manual_restrictions(m, restrictions_dir):
    """Собираем из gpx файлов ограничения, созданные вручную, и добавляем на карту"""

    # Ограничения собираем из GPX-файлов
    all_restrictions = []
    all_restrictions_names = []
    for restriction_file in os.listdir(restrictions_dir):
        if restriction_file.endswith('.gpx'):
            restriction_path = os.path.join(restrictions_dir, restriction_file)
            parsed_restrictions_from_file = parse_gpx_points(restriction_path, is_restriction=True)
            all_restrictions.extend(parsed_restrictions_from_file)
            # продублируем имя файла на все линии (треки) файла:
            all_restrictions_names.extend([restriction_file.split('.')[0]] * len(parsed_restrictions_from_file))
    # Ограничения добавляем на карту (разные цвета для разных файлов)
    colors = ['red']  # ['darkred', 'purple', 'orange']  # Цвета для разных файлов
    for i, restriction in enumerate(all_restrictions):
        folium.PolyLine(
            restriction,
            color=colors[i % len(colors)],
            weight=3,
            opacity=0.75,
            # dash_array='10, 5',
            tooltip=f"<b>Аттеншен плиз!</b> {all_restrictions_names[i]}"
        ).add_to(m)

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

def create_combined_map(tracks_dir, restrictions_dir, output_file="index.html"):
    """Создает карту с тепловым слоем и ограничениями"""

    # 1. Собираем все точки
    all_points = get_tracks(tracks_dir)

    # 2. Создаем карту
    avg_lat = sum(p[0] for p in all_points) / len(all_points)
    avg_lon = sum(p[1] for p in all_points) / len(all_points)
    m = folium.Map(location=[avg_lat, avg_lon], tiles="CartoDB Voyager", zoom_start=12)

    # 3. Добавляем ограничения на карту
    restrictions = None
    if 'mos_res.json' not in os.listdir():
        restrictions = create_mos_res_json()
    else:
        with open('mos_res.json', 'r') as f:
            restrictions = json.load(f)
    restrictions = transform_to_geojson(restrictions)
    # 3.1 Планируемые работы по data.mos.ru
    folium.GeoJson(restrictions[0]).add_to(m)
    # 3.2 Хороший асфальт
    folium.GeoJson(restrictions[1], color='green', weight=3).add_to(m)
    # 3.3 Плохой асфальт на базе улиц data.mos.ru
    get_tooltip = GeoJsonTooltip(
        fields=["display_name"],  # Поля из feature["properties"]
        aliases=["Ахтунг!"],  # Подписи к полям
        localize=True,
        sticky=True
    )
    folium.GeoJson(restrictions[2], color='red', weight=3, opaqcity=0.75, tooltip=get_tooltip).add_to(m)

    # 4. Добавляем ограничения собранные вручную
    add_manual_restrictions(m, restrictions_dir)

    # 5. Добавляем тепловую карту
    yell = 'yellow'
    HeatMap(
        all_points,
        max_zoom=8,
        radius=3,
        # gradient={0.4: 'blue', 0.9: yell, 1: 'red'},
        blur=2
    ).add_to(m)

    # 6. Добавляем легенду
    # add_legend(m)

    # 7. Добавляем контроль местоположения
    folium.plugins.LocateControl(keepCurrentZoomLevel=True).add_to(m)

    # 8. Сохраняем карту
    m.save(output_file)
    print(f"Карта сохранена в файл: {output_file}")

    return


if __name__ == "__main__":
    # пути к папкам
    TRACKS_DIR = "./tracks"  # Папка с GPX-файлами треков
    RESTRICTIONS_DIR = "./tracks/restrictions"  # Папка с файлами ограничений

    # Создаем карту с треками и ограничениями
    create_combined_map(TRACKS_DIR, RESTRICTIONS_DIR)

    # Добавляем Google Analytics
    add_google_analytics()

    # Открытие в браузере
    webbrowser.open('index.html')