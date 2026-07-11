import os
import webbrowser
import gdown
import gpxpy
import folium
from folium import plugins
import tempfile
from pathlib import Path

from config import settings


# Папка для сохранения треков (временная)
DOWNLOAD_DIR = tempfile.mkdtemp(prefix="gpx_tracks_")

# Цвета для разных треков (если треков больше, цвета будут повторяться)
COLORS = ["red", "blue", "green", "purple", "orange", "darkred", "lightred",
          "beige", "darkblue", "darkgreen", "cadetblue", "darkpurple", "white",
          "pink", "lightblue", "lightgreen", "gray", "black", "lightgray"]

# ====== 1. СКАЧИВАНИЕ ПАПКИ ======
print(f"📥 Скачивание папки из Google Drive...")
print(f"   URL: {settings.GPX_FOLDER}")
print(f"   В папку: {DOWNLOAD_DIR}")

# gdown умеет скачивать целые папки рекурсивно
# Флаг --folder указывает, что это папка, а не файл
gdown.download_folder(
    settings.GPX_FOLDER,
    output=DOWNLOAD_DIR,
    quiet=False,  # Показывать прогресс
    use_cookies=False
)

print(f"✅ Скачивание завершено! Файлы сохранены в: {DOWNLOAD_DIR}")

# ====== 2. ПОИСК GPX-ФАЙЛОВ ======
gpx_files = []
for root, dirs, files in os.walk(DOWNLOAD_DIR):
    for file in files:
        if file.lower().endswith(".gpx"):
            gpx_files.append(os.path.join(root, file))

print(f"📁 Найдено GPX-файлов: {len(gpx_files)}")

if not gpx_files:
    print("❌ GPX-файлы не найдены в скачанной папке.")
    exit()

# ====== 3. ПАРСИНГ GPX И ПОСТРОЕНИЕ КАРТЫ ======
# Создаём карту с центром в средних координатах (позже обновим)
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

    # Если точек нет, пропускаем
    if not points:
        print(f"   В файле {os.path.basename(gpx_path)} нет точек.")
        continue

    # Добавляем линию трека на карту
    # folium.PolyLine(
    #     points,
    #     color=color,
    #     weight=4,
    #     opacity=0.8,
    #     popup=os.path.basename(gpx_path),
    #     tooltip=os.path.basename(gpx_path)
    # ).add_to(m)


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

# ====== 4. НАСТРОЙКА ЦЕНТРА КАРТЫ ======
if all_points:
    avg_lat = sum(p[0] for p in all_points) / len(all_points)
    avg_lon = sum(p[1] for p in all_points) / len(all_points)
    m.location = [avg_lat, avg_lon]

    # слой для управления отображением
    folium.LayerControl().add_to(m)

    #  Fullscreen для удобства
    plugins.Fullscreen().add_to(m)

# ====== 5. СОХРАНЕНИЕ КАРТЫ ======
output_file = "output/check_tracks.html"
m.save(output_file)
print(f"\n🗺️ Карта сохранена в файл: {output_file}")
webbrowser.open(str(output_file))

# ====== 6. ОЧИСТКА (опционально) ======
# Раскомментируйте, если хотите удалять скачанные файлы после создания карты
# import shutil
# shutil.rmtree(DOWNLOAD_DIR)
# print(f"🧹 Временная папка {DOWNLOAD_DIR} удалена.")