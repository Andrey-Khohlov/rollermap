from datetime import datetime, timedelta
import os
from pathlib import Path
import webbrowser
import gdown
import gpxpy
import folium
from folium import plugins

from config import TRACKS_DIR, settings
from main import extract_points, filter_points_by_distance


DOWNLOAD_DIR = 'tracks/temp' # Папка для сохранения треков 
OUTPUT_FILE = "output/check_tracks.html"

# Цвета для разных треков
COLORS = ["red", "blue", "green", "purple", "orange", "darkred", "lightred",
          "beige", "darkblue", "darkgreen", "cadetblue", "darkpurple", "white",
          "pink", "lightblue", "lightgreen", "gray", "black", "lightgray"]

# 1. 
print(f"📥 Скачивание папки из Google Drive...")
print(f"   URL: {settings.GPX_FOLDER}")
print(f"   В папку: {DOWNLOAD_DIR}")

gdown.download_folder(
    settings.GPX_FOLDER,
    output=DOWNLOAD_DIR,
    quiet=False,  # Показывать прогресс
    use_cookies=False
)

print(f"Скачивание завершено. Файлы сохранены в: {DOWNLOAD_DIR}")

# DOWNLOAD_DIR = 'tracks' 
# period_days = 2
# gpx_files = []
# cutoff = (datetime.now() - timedelta(days=period_days)).timestamp()
# for track_file in Path(TRACKS_DIR).iterdir():  
#     if track_file.suffix.lower() != ".gpx":
#         continue
#     if track_file.stat().st_ctime < cutoff:
#         continue
#     gpx_files.append(os.path.join(DOWNLOAD_DIR, track_file))

# 2. 
gpx_files = []
for root, dirs, files in os.walk(DOWNLOAD_DIR):
    for file in files:
        if file.lower().endswith(".gpx"):
            gpx_files.append(os.path.join(root, file))

print(f"Найдено {len(gpx_files)} GPX-файлов.")

if not gpx_files:
    print("GPX-файлы не найдены в скачанной папке.")
    exit()

#  3. 
map_center = [0, 0]
m = folium.Map(location=map_center, zoom_start=12, tiles="OpenStreetMap")

all_points = []
for idx, gpx_path in enumerate(gpx_files):
    color = COLORS[idx % len(COLORS)]
    print(f"   Обработка: {os.path.basename(gpx_path)} (цвет: {color})")

    with open(gpx_path, "r", encoding="utf-8") as f:
        gpx = gpxpy.parse(f)

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append((point.latitude, point.longitude))
                all_points.append((point.latitude, point.longitude))
                folium.CircleMarker(
                    location=(point.latitude, point.longitude),
                    radius=0.5,
                    color=color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.7
                ).add_to(m)

    if not points:
        print(f"   В файле {os.path.basename(gpx_path)} нет точек.")
        continue

    # Добавляет маркер в начало и конец трека (опционально)
    folium.Marker(
        points[0],
        popup=f"Старт: {os.path.basename(gpx_path)}",
        icon=folium.Icon(color="green", icon="play")
    ).add_to(m)

    folium.Marker(
        points[-1],
        popup=f"Финиш: {os.path.basename(gpx_path)}",
        icon=folium.Icon(color="red", icon="stop")
    ).add_to(m)

if all_points:
    avg_lat = sum(p[0] for p in all_points) / len(all_points)
    avg_lon = sum(p[1] for p in all_points) / len(all_points)
    m.location = [avg_lat, avg_lon]

    folium.LayerControl().add_to(m)
    plugins.Fullscreen().add_to(m)

m.save(OUTPUT_FILE)
print(f"\nКарта сохранена в файл: {OUTPUT_FILE}")
webbrowser.open(str(OUTPUT_FILE))
