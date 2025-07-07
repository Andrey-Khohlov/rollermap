import gpxpy
import pandas as pd
import folium
from folium.plugins import HeatMap
import os


def parse_gpx(file_path):
    """Извлечение точек трека из GPX файла"""
    with open(file_path, 'r') as gpx_file:
        gpx = gpxpy.parse(gpx_file)

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append({
                    'latitude': point.latitude,
                    'longitude': point.longitude,
                    'elevation': point.elevation,
                    'time': point.time
                })
    return pd.DataFrame(points)


def process_gpx_files(directory):
    """Обработка всех GPX файлов в директории"""
    all_points = []

    for filename in os.listdir(directory):
        if filename.endswith('.gpx'):
            file_path = os.path.join(directory, filename)
            df = parse_gpx(file_path)
            all_points.append(df)

    return pd.concat(all_points, ignore_index=True)


def create_heatmap(gpx_data, output_file='heatmap.html'):
    """Создание тепловой карты с помощью Folium"""
    # Центрируем карту на средних координатах
    mean_lat = gpx_data['latitude'].mean()
    mean_lon = gpx_data['longitude'].mean()

    m = folium.Map(location=[mean_lat, mean_lon], zoom_start=13)

    # Подготовка данных для тепловой карты
    heat_data = [[row['latitude'], row['longitude']] for index, row in gpx_data.iterrows()]

    # Добавление тепловой карты
    HeatMap(heat_data, radius=15).add_to(m)

    # Сохранение в HTML файл
    m.save(output_file)
    return m


if __name__ == '__main__':
    # Укажите путь к папке с GPX файлами
    gpx_directory = '/home/xgb/ролллермаршруты/'

    # Обработка файлов
    gpx_data = process_gpx_files(gpx_directory)

    # Создание тепловой карты
    heatmap = create_heatmap(gpx_data)

    # Открытие в браузере (опционально)
    import webbrowser

    webbrowser.open('heatmap.html')
