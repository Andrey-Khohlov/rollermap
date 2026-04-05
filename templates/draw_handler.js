<script>
(function() {
    // Вспомогательная функция для получения IP-адреса пользователя
    function getUserIp() {
        return fetch('https://api.ipify.org?format=json')
            .then(response => response.json())
            .then(data => data.ip)
            .catch(error => {
                console.error('Не удалось получить IP:', error);
                return null; // если не получилось, отправляем null
            });
    }

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

        // --- ОБРАБОТЧИК СОЗДАНИЯ ФИГУРЫ ---
        map.on(L.Draw.Event.CREATED, function(event) {
            var layer = event.layer;
            var drawnGeoJSON = layer.toGeoJSON();
            var userName = prompt("Введите ваше имя:", "") || "Аноним";
            var description = prompt("Опишите затруднение:", "бордюринг, асфальт разобрали, полный ахтунг!");

            // Сначала получаем IP, потом отправляем все данные
            getUserIp().then(ip => {
                var dataToSend = {
                    geojson: drawnGeoJSON,
                    user: userName,
                    description: description,
                    action: "create",
                    ip_address: ip   // <-- добавлен IP
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
        });

        // --- ОБРАБОТЧИК УДАЛЕНИЯ ФИГУРЫ ---
        map.on(L.Draw.Event.DELETED, function(event) {
            var deletedLayers = event.layers;
            var userName = prompt("Введите ваше имя для подтверждения удаления:", "") || "Аноним";
            var description = prompt("📉 Удаляем проблему? Что там сейчас:", "бордюры вернули, асфальт положили, яму закопали, можногнать! ✅");

            // Сначала получаем IP, потом отправляем данные по каждому удалённому слою
            getUserIp().then(ip => {
                deletedLayers.eachLayer(function(layer) {
                    var deletedGeoJSON = layer.toGeoJSON();
                    var dataToSend = {
                        geojson: deletedGeoJSON,
                        user: userName,
                        description: description,
                        action: "delete",
                        ip_address: ip   // <-- добавлен IP
                    };

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
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
</script>