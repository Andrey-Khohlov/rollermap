
import logging
import os
import webbrowser
import gpxpy
import geopandas as gpd
import folium
import branca.colormap as cm
from shapely.geometry import Point, LineString
from collections import defaultdict
import pyrosm
from tqdm import tqdm

from config import (
    settings,
    DEV_MODE,  
    )

logger = logging.getLogger(__name__)

if DEV_MODE:
    logger.info("Включен режим DEV_MODE")

# ------------------------ 1. Конфигурация ------------------------
PBF_PATH = "./data/moscow.osm.pbf"          # путь к вашему PBF-файлу
GPX_FOLDER = "./tracks/"                    # папка с GPX-треками
OUTPUT_HTML = "moscow_traffic_intensity.html"

# ------------------------ 2. Загрузка дорожной сети из PBF через Pyrosm ------------------------
print("Загрузка дорожной сети из PBF...")
osm = pyrosm.OSM(PBF_PATH)

# Загружаем рёбра с фильтром, подходящим для роллеров (пешеходные, вело, жилые, парковые)
osm_keys_to_keep = "highway"
custom_filter = dict(
        # Areas are not parsed for networks by default
        area=['yes'],
        # OSM "highway" elements that have these tags, cannot be cycled
        highway=['steps', 'corridor', 'elevator', 'escalator', 'motor', 'proposed',
                 'construction', 'abandoned', 'platform', 'raceway', 'motorway', 'motorway_link'],
        # Do not include private roads
        service=['private']
    )

# In this case we want to EXCLUDE all the rows that have tags matching the criteria above
filter_type = "exclude"

# Run and get all cycling roads
gdf_edges = osm.get_data_by_custom_criteria(
    custom_filter=custom_filter, 
    osm_keys_to_keep=osm_keys_to_keep,
    filter_type=filter_type
    )

# Перепроецируем в метрическую систему (EPSG:3857 или 32637) для точных расстояний
gdf_edges = gdf_edges.to_crs("EPSG:3857")

print(f"Загружено {len(gdf_edges)} рёбер.")

# Добавим уникальный идентификатор для каждого ребра (используем индекс)
gdf_edges['edge_id'] = gdf_edges.index

# Сохраним геометрию в исходной системе (WGS84) для отображения на Folium
gdf_edges_wgs84 = gdf_edges.to_crs("EPSG:4326")

# ------------------------ 3. Парсинг GPX-файлов ------------------------
def parse_gpx_folder(folder):
    """Читает все GPX-файлы и возвращает список точек с именем файла"""
    points = []
    gpx_files = [fname for fname in os.listdir(folder) if fname.endswith('.gpx')]
    if DEV_MODE:
        gpx_files = gpx_files[:200]
    for fname in tqdm(gpx_files):
        if not fname.lower().endswith('.gpx'):
            continue
        with open(os.path.join(folder, fname), 'r', encoding='utf-8') as f:
            gpx = gpxpy.parse(f)
        for track in gpx.tracks:
            for segment in track.segments:
                for pt in segment.points:
                    points.append({
                        'lat': pt.latitude,
                        'lon': pt.longitude,
                        'file': fname
                    })
    return points

print("Парсинг GPX-файлов...")
points = parse_gpx_folder(GPX_FOLDER)
print(f"Найдено {len(points)} точек.")

if not points:
    print("Нет точек. Проверьте папку с GPX.")
    exit()

# Создаём GeoDataFrame точек в WGS84
gdf_points = gpd.GeoDataFrame(
    points,
    geometry=gpd.points_from_xy([p['lon'] for p in points], [p['lat'] for p in points]),
    crs="EPSG:4326"
)
# Перепроецируем в метрическую систему для точного поиска
gdf_points_proj = gdf_points.to_crs("EPSG:3857")

# ------------------------ 4. Map‑matching (проекция точек на ближайшее ребро) ------------------------
print("Выполняется map‑matching...")
# Используем пространственный индекс sjoin_nearest (требуется geopandas >= 0.10)
# Ищем для каждой точки ближайшее ребро в радиусе 30 метров (можно настроить)
matched = gpd.sjoin_nearest(
    gdf_points_proj,
    gdf_edges,
    how="left",
    distance_col="dist_to_edge"
)

# Оставляем только те точки, которые попали в заданный радиус (м)
MAX_DIST_METERS = 30
matched = matched[matched["dist_to_edge"] <= MAX_DIST_METERS]
 
# Оставляем только те группы, где размер >= contact_num
contact_num = 3
matched = matched[matched.groupby('geometry')['geometry'].transform('size') >= contact_num]

# Удаляем дубликаты точек, если они есть (оставляем первое совпадение)
matched = matched.drop_duplicates(subset=["geometry"])

print(f"Сопоставлено {len(matched)} точек с дорогами.")

# ------------------------ 5. Агрегация интенсивности ------------------------
# Для каждого ребра запоминаем, какие файлы (треки) по нему проезжали
edge_tracks = defaultdict(set)

for _, row in matched.iterrows():
    edge_id = row["edge_id"]
    fname = row["file"]
    edge_tracks[edge_id].add(fname)

# Преобразуем в интенсивность = количество уникальных треков
intensity = {edge_id: len(tracks) for edge_id, tracks in edge_tracks.items()}

print(f"Найдено {len(intensity)} рёбер с ненулевой интенсивностью.")

# Добавим колонку интенсивности в основной GeoDataFrame (для всех рёбер)
gdf_edges_wgs84["intensity"] = gdf_edges_wgs84["edge_id"].map(intensity).fillna(0).astype(int)

# ------------------------ 6. Визуализация на Folium ------------------------
print("Построение карты...")
# Центр карты – Москва
m = folium.Map(
    location=[55.7558, 37.6173], 
    crs="EPSG3395",
    tiles=f"https://tiles.api-maps.yandex.ru/v1/tiles/?x={{x}}&y={{y}}&z={{z}}&lang=ru_RU&l=map&apikey={settings.YANDEX_API_KEY}",
    attr="Яндекс.Карты",
    zoom_start=12,
    )

# ----------------------------

# Цветовая шкала
max_int = gdf_edges_wgs84["intensity"].max()
if max_int == 0:
    print("Нет данных для отображения.")
    exit()

colormap = cm.LinearColormap(
    colors=["green", "yellow", "red"],
    vmin=1,
    vmax=max_int,
    caption="Количество проездов"
)

# Берём только рёбра с интенсивностью > 0 и разбиваем мультилинии
gdf_to_plot = gdf_edges_wgs84[gdf_edges_wgs84["intensity"] > 0].copy()
# Оставляем только LineString и MultiLineString (отбрасываем Polygon и другие)
gdf_to_plot = gdf_to_plot[gdf_to_plot.geometry.type.isin(['LineString', 'MultiLineString'])]
print(f"После фильтра осталось {len(gdf_to_plot)} ребер из {len(intensity)} с интенсивностью > 0.")
# explode() превращает каждую часть MultiLineString в отдельную строку
# index_parts=True добавляет индекс части, чтобы избежать дублирования индексов
gdf_to_plot = gdf_to_plot.explode(index_parts=True)

# Теперь все геометрии должны быть LineString
for _, row in gdf_to_plot.iterrows():
    coords = [(lat, lon) for lon, lat in row.geometry.coords]
    folium.PolyLine(
        locations=coords,
        color=colormap(row["intensity"]),
        weight=3,
        opacity=0.8,
        popup=f"Проездов: {row['intensity']}"
    ).add_to(m)

# ---------------------------- отображение всех дорог

# # Определяем максимальную интенсивность для цветовой шкалы
# max_int = gdf_edges_wgs84["intensity"].max()
# if max_int == 0:
#     print("Внимание: нет проездов, показываем только серые улицы.")
#     # Всё равно можно показать серые улицы, задав фиктивную шкалу
#     colormap = cm.LinearColormap(
#         colors=["gray", "gray"],  # не используется, но для легенды
#         vmin=0, vmax=1,
#         caption="Интенсивность проездов (нет данных)"
#     )
# else:
#     colormap = cm.LinearColormap(
#         colors=["green", "yellow", "red"],
#         vmin=0,
#         vmax=max_int,
#         caption="Количество проездов"
#     )

# # Разбиваем все мультилинии на простые линии (для всех рёбер)
# gdf_all_lines = gdf_edges_wgs84.explode(index_parts=True)

# # 1. Сначала рисуем ВСЕ улицы серым цветом (толщина 1, прозрачность 0.3)
# #    Это будет фоновый слой.
# for _, row in gdf_all_lines.iterrows():
#     coords = [(lat, lon) for lon, lat in row.geometry.coords]
#     folium.PolyLine(
#         locations=coords,
#         color="blue",
#         weight=3,
#         opacity=0.9,
#         popup=f"Тип: {row.get('highway', 'unknown')}"  # можно убрать, если нет колонки
#     ).add_to(m)

# # 2. Затем рисуем ТОЛЬКО ТЕ рёбра, где интенсивность > 0, цветными линиями
# #    (они будут поверх серых)
# gdf_intense = gdf_all_lines[gdf_all_lines["intensity"] > 0]

# for _, row in gdf_intense.iterrows():
#     coords = [(lat, lon) for lon, lat in row.geometry.coords]
#     folium.PolyLine(
#         locations=coords,
#         color=colormap(row["intensity"]),
#         weight=3,
#         opacity=0.9,
#         popup=f"Проездов: {row['intensity']}"
#     ).add_to(m)

# ----------------------------

# Добавляем цветовую шкалу
colormap.add_to(m)

# Сохраняем карту
m.save(OUTPUT_HTML)
logger.info("Folium карта готова")
webbrowser.open(OUTPUT_HTML)

