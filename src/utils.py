import folium

from main import RESTRICTIONS_DIR

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
            logger.info("Успешный ответ dat.mos.ru")
        else:
            logger.warning("Ошибка:", response.status_code, response.text)
    except requests.exceptions.RequestException as e:
        logger.warning("Ошибка запроса:", e)
    return restrictions
    
def add_gov_restrictions(m):
    """Добавляем ограничения, собранные data.mos, на карту"""

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

def add_manual_restrictions(m, restrictions_dir):
    """Собираем из gpx файлов ограничения, созданные вручную, и добавляем на карту"""

    # Ограничения собираем из GPX-файлов
    all_restrictions = []
    all_restrictions_names = []
    for restriction_file in os.listdir(restrictions_dir):
        if restriction_file.endswith('.gpx'):
            restriction_path = os.path.join(RESTRICTIONS_DIR, restriction_file)
            parsed_restrictions_from_file = parse_gpx_points(restriction_path, step=1, is_restriction=True)
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

def add_legend(m):
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
            <p>Тепловая карта треков роллеров 2026</p>
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

    return m

def add_legend_restrictions(m, all_restrictions, all_restrictions_names) -> None:
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