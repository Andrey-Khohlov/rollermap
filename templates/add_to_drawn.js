<script>
(function() {
    function addAllGeoJsonToDrawn() {
        // Проверяем, что Leaflet загружен
        if (typeof L === 'undefined') {
            console.log("Leaflet ещё не загружен, повтор через 200ms");
            setTimeout(addAllGeoJsonToDrawn, 200);
            return;
        }
        
        // Находим карту
        var map = null;
        for (var key in window) {
            if (window[key] && window[key] instanceof L.Map) {
                map = window[key];
                break;
            }
        }
        if (!map) {
            console.log("Карта не найдена, повтор через 200ms");
            setTimeout(addAllGeoJsonToDrawn, 200);
            return;
        }
        
        // Находим FeatureGroup для редактирования (drawnItems)
        var drawnGroup = null;
        for (var key in window) {
            if (key.indexOf('drawnItems_draw_control_') === 0 && window[key] instanceof L.FeatureGroup) {
                drawnGroup = window[key];
                break;
            }
        }
        if (!drawnGroup) {
            console.log("drawnGroup не найдена, повтор через 200ms");
            setTimeout(addAllGeoJsonToDrawn, 200);
            return;
        }
        
        // Перебираем все слои карты
        var addedCount = 0;
        map.eachLayer(function(layer) {
            // Проверяем, является ли слой GeoJSON (по наличию метода toGeoJSON или по свойству)
            // и не добавлен ли он уже в drawnGroup
            if (layer && typeof layer.toGeoJSON === 'function' && !drawnGroup.hasLayer(layer)) {
                // Если это слой-коллекция (L.GeoJSON), то добавляем его дочерние слои
                if (layer.eachLayer) {
                    layer.eachLayer(function(subLayer) {
                        drawnGroup.addLayer(subLayer);
                        addedCount++;
                    });
                } else {
                    drawnGroup.addLayer(layer);
                    addedCount++;
                }
            }
        });
        if (addedCount > 0) {
            console.log("Добавлено слоёв в редактируемую группу: " + addedCount);
        } else {
            console.log("Не найдено GeoJSON слоёв для добавления");
        }
    }
    
    // Запускаем после полной загрузки DOM и ресурсов
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', addAllGeoJsonToDrawn);
    } else {
        addAllGeoJsonToDrawn();
    }
})();
</script>