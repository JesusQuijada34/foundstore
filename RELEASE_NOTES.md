# Foundstore v1.2-26.08-22.20

Release de **Foundstore Fluthin Store** para `Danenone`, con publisher `Influent`, author `JesusQuijada34` y plataforma de proyecto `AlphaCube`. Esta publicación se compila como asset Linux/Danenone para su incorporación controlada en la imagen de Danenone.

## Novedades

Foundstore incluye ahora una aplicación Qt6 con catálogo desde la API pública, caché local de 15 minutos y recursos remotos con geometría reservada. Las tarjetas usan banner 16:9, icono e identidad consistente; la ficha muestra el README Markdown a la derecha con selección y copia de código.

La configuración persiste el tema claro u oscuro, cinco acentos, los modos Compacto, Milimetrado y MacOS Style, además de cuadrículas de tres, cuatro o cinco columnas. Las acciones de paquete conservan confirmación local, validación de release y cancelación cooperativa; Actualizar sólo aparece cuando existe un tag de release más reciente.

## Validación

El paquete se valida antes de publicar como ZIP `.iflapp` con `details.xml`, recursos y binarios esperados. La suite de aplicación cubre catálogo, caché, preferencias, renderizado Markdown, acciones y geometría de tarjetas. El release sólo debe contener el artefacto Danenone validado y usar este texto como cuerpo exacto.
