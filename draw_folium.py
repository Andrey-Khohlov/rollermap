import folium
from folium.plugins import Draw
from branca.element import Template, MacroElement

# Создаем карту
m = folium.Map(location=[55.75, 37.61], zoom_start=12)

# Добавляем инструмент рисования
Draw(
    export=True,
    draw_options={
        "polyline": True,
        "polygon": False,
        "rectangle": False,
        "circle": False,
        "marker": False,
    },
).add_to(m)

# HTML-форма с исправленным JavaScript
template = """
{% macro html(this, kwargs) %}
<div id="save-panel" style="
    position: fixed;
    bottom: 50px;
    left: 10px;
    z-index: 1000;
    background: white;
    padding: 10px;
    border-radius: 5px;
    box-shadow: 0 0 5px rgba(0,0,0,0.2);
">
    <label for="file_name"><b>Название файла:</b></label>
    <input type="text" id="file_name" value="traffic_obstructions.geojson" style="margin-bottom: 5px;">
    <br>
    <label for="description"><b>Описание:</b></label>
    <input type="text" id="description" placeholder="Например: Ремонт дороги" style="margin-bottom: 5px;">
    <br>
    <button onclick="saveWithDescription()" style="
        background: #4CAF50;
        color: white;
        border: none;
        padding: 5px 10px;
        border-radius: 3px;
        cursor: pointer;
    ">Сохранить с описанием</button>
</div>

<script>
function saveWithDescription() {
    // Получаем данные с карты
    const drawnItems = window.map.getData();
    if (!drawnItems || !drawnItems.features || drawnItems.features.length === 0) {
        alert("Сначала нарисуйте линию на карте!");
        return;
    }

    // Добавляем описание в GeoJSON
    const description = document.getElementById('description').value;
    const fileName = document.getElementById('file_name').value || 'traffic_obstructions.geojson';

    const updatedGeoJSON = {
        ...drawnItems,
        features: drawnItems.features.map(feature => ({
            ...feature,
            properties: {
                ...feature.properties,
                description: description
            }
        }))
    };

    // Создаем и скачиваем файл
    const blob = new Blob([JSON.stringify(updatedGeoJSON, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = fileName;
    link.click();
}
</script>
{% endmacro %}
"""

# Добавляем форму на карту
macro = MacroElement()
macro._template = Template(template)
m.add_child(macro)

# Сохраняем карту
m.save("map_with_save_button.html")
print("Карта сохранена. Откройте map_with_save_button.html в браузере.")