import json
import webbrowser
import pandas as pd
import folium

def get_last_n_rows_from_public_sheet(sheet_id, n=10, gid=0):
    """
    Загружает публичную Google Таблицу как CSV и возвращает последние n строк.
    """
    url = f'https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}'
    df = pd.read_csv(url)
    
    if df.empty:
        return []
    
    # Берём последние n строк
    last_n = df.tail(n)
    return last_n


def parse_geojson_line(geojson_str):
    """Парсит GeoJSON и возвращает координаты LineString (даже если обёрнут в Feature)."""
    try:
        data = json.loads(geojson_str)
        
        # Если это Feature, берём его geometry
        if data.get('type') == 'Feature':
            geometry = data.get('geometry')
            if geometry and geometry.get('type') == 'LineString':
                return geometry.get('coordinates', [])
            else:
                print(f"Предупреждение: у Feature нет LineString в geometry")
                return None
        
        # Если сразу LineString
        elif data.get('type') == 'LineString':
            return data.get('coordinates', [])
        
        else:
            print(f"Предупреждение: неизвестный тип {data.get('type')}")
            return None
    except json.JSONDecodeError as e:
        print(f"Ошибка парсинга JSON: {e}")
        return None


def plot_lines_on_map(lines_data, map_center=None, zoom_start=12):
    """Строит карту folium с линиями и подписями."""
    if not lines_data:
        print("Нет данных для отображения.")
        return None

    # Вычисляем центр карты, если не задан
    if map_center is None:
        all_lats, all_lons = [], []
        for _, coords in lines_data:
            for lon, lat in coords:
                all_lats.append(lat)
                all_lons.append(lon)
        if all_lats and all_lons:
            map_center = [sum(all_lats)/len(all_lats), sum(all_lons)/len(all_lons)]
        else:
            map_center = [0, 0]

    m = folium.Map(location=map_center, zoom_start=zoom_start)

    for row_idx, coords in lines_data:
        # folium требует [lat, lon]
        polyline_points = [(lat, lon) for lon, lat in coords]

        folium.PolyLine(
            locations=polyline_points,
            color='blue',
            weight=3,
            opacity=0.8,
            tooltip=f"Строка {row_idx}",
            popup=f"Строка {row_idx}"
        ).add_to(m)

        # Маркер с номером строки в начале линии
        if polyline_points:
            folium.Marker(
                location=polyline_points[0],
                icon=folium.DivIcon(html=f'<div style="font-size: 12pt; color: red;">{row_idx}</div>'),
                tooltip=f"Строка {row_idx}"
            ).add_to(m)

    return m


def main():
    # Параметры
    SHEET_ID = '1v2d56Lw8htsZEETqO5TndjDwesSlSNJLVuaMetdewU4'  # из ссылки
    GID = 0                          # идентификатор листа (обычно 0)
    N = 2                          # сколько последних строк взять
    COLUMN_GEOJSON = 'GeoJSON'       # имя столбца с геоданными

    # 1. Читаем данные
    df = get_last_n_rows_from_public_sheet(SHEET_ID, N, GID)
    if df.empty:
        print("Таблица пуста или не найдена.")
        return

    # 2. Обрабатываем строки
    lines_data = []
    # реальные индексы строк в таблице (учитываем, что первая строка — заголовок)
    # для подписей используем порядковый номер среди выбранных
    for i, (idx, row) in enumerate(df.iterrows(), start=1):
        geojson_str = str(row.get(COLUMN_GEOJSON, '')).strip()
        if not geojson_str:
            print(f"Строка {i}: пустое значение в столбце '{COLUMN_GEOJSON}'")
            continue

        coords = parse_geojson_line(geojson_str)
        if coords is None:
            print(f"Строка {i}: не удалось распарсить GeoJSON")
            continue

        lines_data.append((i, coords))

    if not lines_data:
        print("Нет корректных GeoJSON линий для отображения.")
        return

    # 3. Строим карту
    map_obj = plot_lines_on_map(lines_data)
    if map_obj:
        map_obj.save('check_points.html')
        print("✅ Карта сохранена в map_with_lines.html")
    webbrowser.open('check_points.html')

if __name__ == '__main__':
    main()