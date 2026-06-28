<script>
(function() {
    // Вспомогательная функция для получения IP
    function getUserIp() {
        return fetch('https://api.ipify.org?format=json')
            .then(response => response.json())
            .then(data => data.ip)
            .catch(error => {
                console.error('Не удалось получить IP:', error);
                return null;
            });
    }

    // функция для получения fingerprint через ThumbmarkJS
    function getFingerprint() {
        const data = [
            navigator.userAgent,
            screen.width + 'x' + screen.height,
            screen.colorDepth,
            navigator.language,
            new Date().getTimezoneOffset(),
            navigator.hardwareConcurrency || '',
            navigator.deviceMemory || ''
        ];
        let hash = 0;
        const str = data.join('|');
        for (let i = 0; i < str.length; i++) {
            hash = ((hash << 5) - hash) + str.charCodeAt(i);
            hash |= 0;
        }
        return Math.abs(hash).toString(36);
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
            var description = prompt("Опишите затруднение:", "⚠️🚧🕳️🧱 бордюринг, асфальт разобрали, полный ахтунг! 🆘🛼💀");

            // ++ Получаем и IP, и fingerprint параллельно
            Promise.all([getUserIp(), getFingerprint()])
                .then(function([ip, fingerprint]) {
                    var dataToSend = {
                        geojson: drawnGeoJSON,
                        user: userName,
                        description: description,
                        action: "create",
                        ip_address: ip,
                        browser_fingerprint: fingerprint   // <-- добавлено
                    };

                    fetch("{{GAS_URL}}", {
                        method: "POST",
                        mode: "no-cors",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(dataToSend)
                    })
                    .then(function() {
                        console.log("Рисунок отправлен!");
                        layer.bindPopup("✅" + userName + ", пока только тебе видно, как поддержка глянет 🧐⏱️ — зальют в общую карту насовсем.").openPopup();
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
            var description = prompt("📉 Удаляем проблему? Что там сейчас?", "✅🛣️💨😎 бордюры вернули, асфальт положили, яму закопали, можногнать! 🟢🛼⚡🚀🆗 ");

            Promise.all([getUserIp(), getFingerprint()])
                .then(function([ip, fingerprint]) {
                    deletedLayers.eachLayer(function(layer) {
                        var deletedGeoJSON = layer.toGeoJSON();
                        var dataToSend = {
                            geojson: deletedGeoJSON,
                            user: userName,
                            description: description,
                            action: "delete",
                            ip_address: ip,
                            browser_fingerprint: fingerprint
                        };

                        fetch("{{GAS_URL}}", {
                            method: "POST",
                            mode: "no-cors",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(dataToSend)
                        })
                        .then(function() {
                            console.log("✅ удалено!");
                        })
                        .then(function() {
                            alert("✅" + userName + ", пока только тебе видно, как поддержка глянет 🧐⏱️ — зальют в общую карту насовсем.");
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