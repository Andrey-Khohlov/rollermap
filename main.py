import json
import os

import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

import gpxpy
import folium
import requests
from dotenv import load_dotenv
from folium import GeoJsonTooltip
from folium.plugins import HeatMap, Draw
import pyproj


def transform_to_geojson(input_data):
    """
    Преобразует данные из формата JSON в формат GeoJSON.
    Возвращает список словарей:
    асфальт планируемый к ремонту, новый асфальт, плохой асфальт.
    """

    # Новый асфальт по global_id data.mos.ru работы начаты
    new_asphalt_ids = [2721481373, 2722035600, 2722025415, 2721217470, 1132362475, 2722035611, 2757253622, 2721220029, 2722035035]

    # Плохой асфальт по global_id data.mos.ru
    destroyed_asphalt_ids = {
        2721958914: 'бордюринг 28.07.2025',
        2724150160: 'бордюринг 28.07.2025',
        2722037941: 'бордюринг 28.07.2025',
        2790280623: 'бордюринг 28.07.2025',
        2783496038: 'бордюринг 29.07.2025',
        2790280650: 'бордюринг 29.07.2025',
        2722221944: 'бордюринг 07.07, 31.07',
        2722081144: 'бордюринг 02.08',
        2721615482: 'бордюринг, четная сторона домов проезжаема 02.08',
        2722221945: 'бордюринг 16.08.2025',
        2721220076: 'бордюринг 16.08.2025',
        2721477917: 'снят асфальт, 17.08',
        2721486659: 'снят асфальт, 17.08',
        2721814959: 'снят асфальт, 17.08',
        2722035137: 'снят асфальт 22.08, 24.07',
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

def get_tracks(tracks_dir, period_days=365) -> list:
    """
    Собираем все точки треков
    """
    one_month_ago_timestamp = (datetime.now()- timedelta(days=period_days)).timestamp()
    all_points = []
    for track_file in Path(tracks_dir).iterdir():  # os.listdir(tracks_dir):
        if track_file.name.lower().endswith('.gpx'):
            creation_time = track_file.stat().st_ctime
            if creation_time <= one_month_ago_timestamp:
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
    all_points = all_points[::12 if period_days > 30 else 1]

    if not all_points:
        raise ValueError("Не найдено треков для построения карты!")
    return all_points

def add_legend(m, all_restrictions, all_restrictions_names) -> None:
    """Легенда с динамическим списком ограничений"""

    legend_html = f'''
    <div style="position: fixed; 
                bottom: 20px; left: 20px; 
                width: 200px;
                background: white; 
                border: 1px solid grey;
                padding: 2px 4px;
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
            tooltip=f"{all_restrictions_names[i]}"
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

def add_last_tracks_button():
    """добавляем кнопку из файла last_tracks_button.html"""
    # Читаем index.html
    with open("index.html", "r", encoding="utf-8") as file:
        content = file.read()
    # Код для вставки
    with open('last_tracks_button.html', "r", encoding="utf-8") as file:
        title = file.read()
    # Вставляем после открывающего <body>
    new_content = content.replace("<body>", "<body>" + title)
    # Записываем обратно
    with open("index.html", "w", encoding="utf-8") as file:
        file.write(new_content)

def create_combined_map(tracks_dir, restrictions_dir, output_file="index.html", period_days=180):
    """Создает карту с тепловым слоем и ограничениями"""

    # 1. Собираем все точки
    all_points = get_tracks(tracks_dir, period_days)


    # 2. Создаем карту
    avg_lat = sum(p[0] for p in all_points) / len(all_points)
    avg_lon = sum(p[1] for p in all_points) / len(all_points)
    # tiles_yandex = 'https://core-renderer-tiles.maps.yandex.net/tiles?l=map&x={x}&y={y}&z={z}'
    # m = folium.Map(location=[avg_lat, avg_lon], tiles=tiles_yandex, attr='Яндекс.Карты', zoom_start=12, max_zoom=16)
    # + нужен оффсет для карты Яндекса
    m = folium.Map(location=[avg_lat, avg_lon], tiles="CartoDB Voyager", zoom_start=12, max_zoom=16)


    # 3. Добавляем легенду
    legend_html = """
    <div id="legend" style="
        position: fixed;
        bottom: 10px;
        right: 0px;
        background: white;
        padding: 2px 4px;
        border: 1px solid grey;
        border-radius: 4px;
        box-shadow: 0 0 5px grey;
        z-index: 1000;
    ">
        <div onclick="toggleLegend()" style="cursor: pointer; font-weight: bold; margin: 0; padding: 0; line-height: 1.1;">
            <span id="legend-toggle">▼</span> Легенда
        </div>
        <div id="legend-content">
            <p>Тепловая карта треков роллеров 2025</p>
            <p>Дополнительно отмечены:</p>
            <p><i style="background: royalblue; width: 8px; height: 8px; display: inline-block;"></i> запланированы дорожные работы</p>
            <p><i style="background: red; width: 8px; height: 8px; display: inline-block;"></i> убитый асфальт</p>
            <p><i style="background: green; width: 8px; height: 8px; display: inline-block;"></i> свежий асфальт</p>
            <p>На вкладке <strong>▶ последние треки</strong> отображены</p>
            <p>треки за последние 3 недели</p>
            <p style="text-align: right; margin: 10px 0 0 0; font-size: 0.8em; color: #555;">roller-map@ya.ru</p>
        </div>
    </div>

    <script>
        function toggleLegend() {
            const content = document.getElementById('legend-content');
            const toggle = document.getElementById('legend-toggle');
            if (content.style.display === 'none') {
                content.style.display = 'block';
                toggle.textContent = '▼';
            } else {
                content.style.display = 'none';
                toggle.textContent = '▶';
            }
        }
        // По умолчанию можно скрыть легенду
        document.getElementById('legend-content').style.display = 'none';
        document.getElementById('legend-toggle').textContent = '▶';
    </script>
    """

    m.get_root().html.add_child(folium.Element(legend_html))


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
        aliases=[""],  # Подписи к полям
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

    # Добавляем инструмент рисования
    '''draw_options = {
        "polyline": True,  # Разрешить рисование линий
        "polygon": False,  # Отключить полигоны
        "rectangle": False,
        "circle": False,
        "marker": False,
        "circlemarker": False
    }
    draw = Draw(
        export=True,  # Добавляет кнопку экспорта
        position="topleft",
        draw_options=draw_options,
    )
    draw.add_to(m)'''

    # 8. Сохраняем карту
    m.save(output_file)
    print(f"Карта сохранена в файл: {output_file}")

    return


if __name__ == "__main__":
    # пути к папкам
    TRACKS_DIR = "./tracks"  # Папка с GPX-файлами треков
    RESTRICTIONS_DIR = "./tracks/restrictions"  # Папка с файлами ограничений

    # Создаем карту с треками и ограничениями
    create_combined_map(TRACKS_DIR, RESTRICTIONS_DIR, output_file="index.html", period_days=180)

    # Добавляем Google Analytics
    add_google_analytics()

    # Добавляем заголовок
    add_title()

    # добавляем кнопку последних треков
    add_last_tracks_button()

    # Создаем карту с треками и ограничениями за последние 21 день
    create_combined_map(TRACKS_DIR, RESTRICTIONS_DIR, output_file="last_tracks.html", period_days=21)

    # Добавляем Google Analytics
    add_google_analytics()

    # Добавляем заголовок
    add_title()

    # Открытие в браузере
    webbrowser.open('index.html')