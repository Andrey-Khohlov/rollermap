<script>
(function() {
    function findMapVariable() {
        for (var key in window) {
            if (window[key] && window[key] instanceof L.Map) {
                return window[key];
            }
        }
        return null;
    }

    function init() {
        var map = findMapVariable();
        if (!map) {
            setTimeout(init, 200);
            return;
        }
        console.log("Карта найдена, привязываем обработчик рисования");

        map.on(L.Draw.Event.CREATED, function(event) {
            var layer = event.layer;
            var drawnGeoJSON = layer.toGeoJSON();
            var userName = prompt("Введите ваше имя:", "") || "Аноним";
            var description = prompt("Опишите затруднение:", "бордюринг, асфальт разобрали, полный ахтунг!");

            var dataToSend = {
                geojson: drawnGeoJSON,
                user: userName,
                description: description,
                action: "create" 
            };

            fetch("{{GAS_URL}}", {
                method: "POST",
                mode: "no-cors",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(dataToSend)
            })
            .then(function() {
                console.log("Рисунок отправлен!");
                layer.bindPopup("✅ Сохранено для " + userName + ", публикуем вручную, по возможности в ближайшее время").openPopup();
            })
            .catch(function(error) {
                console.error("Ошибка при отправке:", error);
                layer.bindPopup("❌ Ошибка сохранения").openPopup();
            });
        });
         // <-- НОВЫЙ ОБРАБОТЧИК УДАЛЕНИЯ
         map.on(L.Draw.Event.DELETED, function(event) {
            // e.layers содержит FeatureGroup со всеми удалёнными слоями
            var deletedLayers = event.layers;
            var userName = prompt("Введите ваше имя для подтверждения удаления:", "") || "Аноним";
            var description = prompt("📉 Удаляем проблему? Что там сейчас:", "бордюры вернули, асфальт положили, яму закопали, можногнать! ✅");

            // Проходим по каждому удалённому слою
            deletedLayers.eachLayer(function(layer) {
                var deletedGeoJSON = layer.toGeoJSON();

                var dataToSend = {
                    geojson: deletedGeoJSON,
                    user: userName,
                    description: description,
                    action: "delete" // <-- Указываем, что это удаление
                };

                // Отправляем данные о каждом удалённом объекте
                fetch("{{GAS_URL}}", {
                    method: "POST",
                    mode: "no-cors",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(dataToSend)
                })
                .then(function() {
                    console.log("Информация об удалении отправлена!");
                })
                .catch(function(error) {
                    console.error("Ошибка при отправке информации об удалении:", error);
                });
            });
        });
        // КОНЕЦ НОВОГО ОБРАБОТЧИКА -->
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
</script>