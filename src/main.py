from datetime import datetime, timedelta, date
from io import BytesIO
from pathlib import Path
import re
from typing import NamedTuple
import logging

import webbrowser
import folium

from folium.plugins import HeatMap, Draw
import gpxpy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths (BASE_DIR = project root)
_SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = _SCRIPT_DIR.parent
TRACKS_DIR = BASE_DIR / "tracks"
RESTRICTIONS_DIR = BASE_DIR / "tracks" / "restrictions"

# Map and track config
ZOOM_INITIAL = 12
ZOOM_MAX = 17  # максимальное увеличение карты
DAYS_14 = 14  # дней отображения  для карты последних треков
YEAR_TO_DATE = (date.today() - date(date.today().year, 1, 1)).days
DECIMATION_FACTOR_YEAR = 4  # прореживание для уменьшения размера карты 2026
DECIMATION_FACTOR_14 = 2  # прореживание для уменьшения размера карты 2 нед
HEATMAP_GRADIENT = {
    0.3: "purple",
    0.4: "blue",
    0.5: "cyan",
    0.9: "Yellow",
    1.0: "red",
}

class BoundingBox(NamedTuple):
    lat_min: float  # South
    lat_max: float  # North
    lon_min: float  # East
    lon_max: float  # West


MO_BOX = BoundingBox(54.15, 56.788189, 35.08, 40.11)  # мск область, включая Конаково-Дубна
SVO_BOX = BoundingBox(55.959774, 55.984672, 37.372363, 37.453691)  # аэропорт Шереметьево


def in_box(lat: float, lon: float, box: BoundingBox) -> bool:
    """Точка в bounding box."""
    return box.lat_min < lat < box.lat_max and box.lon_min < lon < box.lon_max


def _point_in_bounds(lat: float, lon: float) -> bool:
    """Точка в МО и не в зоне Шереметьево."""
    return in_box(lat, lon, MO_BOX) and not in_box(lat, lon, SVO_BOX)


def parse_gpx_points(gpx_path: str | Path, step: int, is_restriction: bool = False) -> list:
    """
    Парсит точки из GPX-файла (треки или ограничения).
    Для треков возвращает список [lat, lon]; для ограничений — список линий (каждая линия — список (lat, lon)).
    """
    with open(gpx_path, encoding="utf-8") as gpx_file:
        gpx = gpxpy.parse(gpx_file)

    if is_restriction:
        return [
            [(p.latitude, p.longitude) for p in route.points]
            for route in gpx.routes
        ]

    points: list[tuple[float, float]] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for i, point in enumerate(segment.points):
                if i % step == 0 and _point_in_bounds(point.latitude, point.longitude):
                    points.append((point.latitude, point.longitude))
    if not points and gpx.routes:
        for route in gpx.routes:
            for i, point in enumerate(route.points):
                if i % step == 0 and _point_in_bounds(point.latitude, point.longitude):
                    points.append((point.latitude, point.longitude))
    return points


def get_tracks(period_days: int, step: int) -> list[tuple[float, float]]:
    """Собирает все точки треков за последние period_days дней."""
    cutoff = (datetime.now() - timedelta(days=period_days)).timestamp()
    all_points: list[tuple[float, float]] = []
    for track_file in Path(TRACKS_DIR).iterdir():
        if track_file.suffix.lower() != ".gpx":
            continue
        if track_file.stat().st_ctime > cutoff:
            all_points.extend(parse_gpx_points(track_file, step))
    if not all_points:
        raise ValueError("Не найдено треков для построения карты!")
    return all_points


def _inject_html_snippet(html_path: Path, marker: str, snippet_path: Path, after: bool = True) -> None:
    """Вставляет содержимое snippet_path в html_path: после marker если after=True, иначе перед."""
    content = html_path.read_text(encoding="utf-8")
    snippet = snippet_path.read_text(encoding="utf-8")
    if after:
        new_content = content.replace(marker, marker + snippet)
    else:
        new_content = content.replace(marker, snippet + marker)
    html_path.write_text(new_content, encoding="utf-8")


def add_google_analytics(html_path: Path) -> None:
    """Вставляет Google Analytics перед </head>."""
    _inject_html_snippet(html_path, "</head>", BASE_DIR / "templates" / "google_tag.html", after=False)


def add_title(html_path: Path) -> None:
    """Вставляет заголовок и описание после <head>."""
    _inject_html_snippet(html_path, "<head>", BASE_DIR / "templates" / "title.html", after=True)


def add_last_tracks_button(html_path: Path) -> None:
    """Вставляет кнопку «последние треки» после <body>."""
    _inject_html_snippet(html_path, "<body>", BASE_DIR / "templates" / "last_tracks_button.html", after=True)

def remove_attribution_line(file_path: str | Path, target: str = "attribution", encoding: str = "utf-8") -> bool:
    """
    Удаляет строки, содержащие target, из файла.
    Добавляет "attributionControl": false после строки с "preferCanvas": false,.
    """
    path = Path(file_path)
    if not path.is_file():
        logger.warning("Файл не найден: %s", path)
        return False
    try:
        lines = path.read_text(encoding=encoding).splitlines(keepends=True)
    except OSError as e:
        logger.warning("Ошибка при чтении файла: %s", e)
        return False
    new_lines = [line for line in lines if target not in line]
    if len(new_lines) == len(lines):
        logger.warning("Строка с attribution не найдена. Файл не изменён.")
    out: list[str] = []
    prefer_found = False
    for line in new_lines:
        out.append(line)
        if "preferCanvas" in line:
            out.append('  "attributionControl": false, \n')
            prefer_found = True
    if not prefer_found:
        logger.warning('Строка с preferCanvas не найдена. "attributionControl": false не добавлен.')
    try:
        path.write_text("".join(out), encoding=encoding)
        return True
    except OSError as e:
        logger.warning("Ошибка при записи файла: %s", e)
        return False


def create_combined_map(output_file: str | Path, period_days: int, step: int, zoom_max: int) -> None:
    """Создаёт карту с тепловым слоем треков."""
    all_points = get_tracks(period_days, step)
    n = len(all_points)
    center = (sum(p[0] for p in all_points) / n, sum(p[1] for p in all_points) / n)

    m = folium.Map(
        location=center,
        tiles="CartoDB Voyager",
        zoom_start=ZOOM_INITIAL,
        max_zoom=zoom_max,
    )
    HeatMap(
        all_points,
        max_zoom=10,
        radius=4,
        gradient=HEATMAP_GRADIENT,
        blur=1,
    ).add_to(m)
    folium.plugins.LocateControl(keepCurrentZoomLevel=True).add_to(m)

    # Добавляем плагин Draw (панель рисования)
    draw = Draw(export=False)  # export=False, т.к. мы сами отправляем данные
    draw.add_to(m)

    # Ваш URL веб-приложения Google Apps Script
    GAS_URL = "https://script.google.com/macros/s/AKfycbx1ehJFYDjg8qE2ypRfebGkbsc6IF1v9VOhHTlWQLlPtsa1HRhWYk5kEo2i-OlWHqWw/exec"

    # JavaScript-код, который будет вставлен на страницу
    # html_path= BASE_DIR / "templates" / "js_code.html"
    # js_code = html_path.read_text(encoding="utf-8")
    # js_code = js_code.replace("{{GAS_URL}}", GAS_URL)
    # Теперь используем найденное имя в JavaScript коде
     # JavaScript код, который сам найдёт переменную карты
    js_code = f"""
<script>
(function() {{
    function findMapVariable() {{
        for (var key in window) {{
            if (window[key] && window[key] instanceof L.Map) {{
                return window[key];
            }}
        }}
        return null;
    }}

    function init() {{
        var map = findMapVariable();
        if (!map) {{
            setTimeout(init, 200);
            return;
        }}
        console.log("Карта найдена, привязываем обработчик рисования");

        map.on(L.Draw.Event.CREATED, function(event) {{
            var layer = event.layer;
            var drawnGeoJSON = layer.toGeoJSON();
            var userName = prompt("Введите ваше имя:", "Аноним") || "Аноним";

            var dataToSend = {{
                geojson: drawnGeoJSON,
                user: userName
            }};

            fetch("{GAS_URL}", {{
                method: "POST",
                mode: "no-cors",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify(dataToSend)
            }})
            .then(function() {{
                console.log("Рисунок отправлен!");
                layer.bindPopup("✅ Сохранено для " + userName).openPopup();
            }})
            .catch(function(error) {{
                console.error("Ошибка при отправке:", error);
                layer.bindPopup("❌ Ошибка сохранения").openPopup();
            }});
        }});
    }}

    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', init);
    }} else {{
        init();
    }}
}})();
</script>
"""

    # Внедряем JavaScript в карту с помощью folium.Element
    m.get_root().html.add_child(folium.Element(js_code))
    

    out_path = Path(output_file)
    m.save(str(out_path))
    logger.info("Карта сохранена: %s", out_path)


def _postprocess_html(html_path: Path) -> None:
    """Добавляет аналитику, заголовок, кнопку и убирает attribution."""
    add_google_analytics(html_path)
    add_title(html_path)
    add_last_tracks_button(html_path)
    remove_attribution_line(html_path, target="attribution")


def main() -> None:
    map_configs = [
        (BASE_DIR / "index.html", YEAR_TO_DATE, DECIMATION_FACTOR_YEAR, ZOOM_MAX),
        (BASE_DIR / "last_tracks.html", DAYS_14, DECIMATION_FACTOR_14, ZOOM_MAX),
    ]
    for output_path, period_days, step, zoom_max in map_configs:
        create_combined_map(output_path, period_days=period_days, step=step, zoom_max=zoom_max)
        _postprocess_html(output_path)
    webbrowser.open(str(BASE_DIR / "index.html"))


if __name__ == "__main__":
    main()