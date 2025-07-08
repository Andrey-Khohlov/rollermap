import gpxpy
import folium
from folium.plugins import HeatMap
import os


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


def create_combined_map(tracks_dir, restrictions_dir, output_file="combined_map.html"):
    """Создает карту с тепловым слоем и всеми ограничениями"""
    # 1. Собираем все точки треков
    all_points = []
    for track_file in os.listdir(tracks_dir):
        if track_file.lower().endswith('.gpx'):
            track_path = os.path.join(tracks_dir, track_file)
            all_points.extend(parse_gpx_points(track_path))

    if not all_points:
        raise ValueError("Не найдено треков для построения карты!")

    # 2. Собираем все ограничения
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

    m = folium.Map(location=[avg_lat, avg_lon], tiles="Cartodb Positron", zoom_start=12)

    # 4. Тепловая карта
    HeatMap(
        all_points,
        radius=3,
        gradient={0.4: 'blue', 0.9: 'yellow', 1: 'red'},
        blur=2
    ).add_to(m)

    # 5. Ограничения (разные цвета для разных файлов)
    colors = ['red', 'darkred', 'purple', 'orange']  # Цвета для разных файлов
    for i, restriction in enumerate(all_restrictions):
        folium.PolyLine(
            restriction,
            color=colors[i % len(colors)],
            weight=4,
            opacity=0.8,
            dash_array='10, 5',
            tooltip=f"Ограничение {all_restrictions_names[i]}"
        ).add_to(m)

    # 6. Легенда с динамическим списком ограничений
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
    '''

    for i in range(len(all_restrictions)):
        legend_html += f'''
        <span style="color: {colors[i % len(colors)]}; font-weight: bold;">
        — — —</span> Ограничение {all_restrictions_names[i]}<br>
        '''

    legend_html += '</div>'
    # m.get_root().html.add_child(folium.Element(legend_html))

    m.save(output_file)
    print(f"Карта сохранена в файл: {output_file}")
    return m


# Пример использования
if __name__ == "__main__":
    # Укажите пути к папкам
    TRACKS_DIR = "/home/xgb/ролллермаршруты/"  # Папка с GPX-файлами треков
    RESTRICTIONS_DIR = TRACKS_DIR + "бордюринг/"  # Папка с файлами ограничений

    # Создаем карту
    create_combined_map(TRACKS_DIR, RESTRICTIONS_DIR)

    # Открытие в браузере (опционально)
    import webbrowser

    webbrowser.open('combined_map.html')