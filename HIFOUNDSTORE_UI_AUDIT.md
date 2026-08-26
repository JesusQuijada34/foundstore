# Auditoría de hifoundstore.onrender.com

Fecha: 2026-08-26.

La web desplegada ya entrega `store-preview`, los fondos `foundstore-background-light.jpg` y `foundstore-background-dark.jpg`, `foundstore-theme.js`, el manifest, iconos PNG y splashs. El macro usa el SVG local `/static/foundstore-mark.svg`.

El problema restante observado por navegador es caché de CSS: el documento carga `/static/css/foundstore-v2.css?v=pwa2` y el modo claro conserva `h1` blanco (`rgb(255,255,255)`) sobre la imagen clara, aunque la versión local incluye reglas de contraste final. Se debe subir la query a `pwa3` para obligar a descargar la hoja nueva.

También se confirmó que el CSS servido con `pwa2` carga el fondo claro y que el HTML nuevo ya no contiene el SVG demo; el error visual actual es el color cacheado, no la ruta de la preview.
