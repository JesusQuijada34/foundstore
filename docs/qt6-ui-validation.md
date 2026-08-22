# Validación visual de Foundstore Qt6

## Ejecuciones bajo Xvfb

La primera ejecución confirmó que la ventana arrancaba, pero el titular y la marca heredaban un color oscuro contra un fondo oscuro y el catálogo bloqueaba la interfaz durante la consulta. La segunda ejecución corrigió la legibilidad del encabezado y dejó visible un estado de carga mientras el catálogo se consulta en un hilo Qt separado.

## Próxima validación

La captura posterior debe realizarse después de recibir el catálogo o mediante una fuente de datos de prueba explícita de la propia aplicación. Se debe comprobar la geometría de las filas de resultados, el acceso a la ficha y la confirmación antes de cualquier instalación.

## Catálogo y ficha cargados

El catálogo real completó la consulta y mostró 27 paquetes verificados en filas compactas, con búsqueda, acciones de ficha e instalación y navegación lateral. La navegación a la ficha funciona, pero la captura reveló que `detailTitle` heredaba color oscuro sobre el panel oscuro. Antes de la entrega se debe aplicar un color explícito de alto contraste al título de detalle y tomar una nueva captura de cierre.

## Integración API pública

La aplicación reemplazó el lector directo de `repo.list` para navegación por la API pública de Foundstore. La captura de catálogo confirma nueve paquetes que ya pasan el contrato web, iconos remotos y estrellas GitHub verificadas; por ejemplo, Camera Selfie expone 2 estrellas. La ficha posterior confirma icono, portada 16:9, README y el mismo conteo verificado desde `GET /api/v1/catalog/camera`. La instalación permanece separada y conserva la confirmación local antes de usar el gestor Fluthin.

## Estabilidad de recursos y geometría

Los iconos y portadas pasan ahora por un recorte Qt con radio fijo y borde consistente; sus marcos mantienen el tamaño de reserva durante carga y fallos. La ficha se aloja en un área con desplazamiento vertical para que una portada o README largo no desplace ni comprima controles. Durante la corrección se detectó y reparó un error de tipo entre `QRect` y `QRectF` que abortaba la aplicación al pintar recursos remotos. La captura de cierre muestra las nueve fichas con iconos recortados de forma uniforme, radios de 8 a 14 píxeles y acciones alineadas.

La ficha de detalle posterior conserva la misma cuadrícula: icono de 94 píxeles, cabecera fija, portada de 480 × 270 píxeles, aviso y README en secuencia vertical desplazable. Esta composición evita que una imagen de origen o un README extenso determine el ancho, el alto o la posición de las acciones de la aplicación.

## Resultados de tienda y caché de 15 minutos

El catálogo usa ahora fichas de 392 píxeles en una cuadrícula de dos columnas en pantallas amplias y una columna cuando no hay espacio. Cada ficha conserva una cabecera de aplicación, estrellas verificadas, una previsualización 16:9 y acciones alineadas, sin barra de desplazamiento horizontal. El cliente conserva catálogo y fichas en `XDG_CACHE_HOME/influent-danenone/foundstore`, reutiliza datos durante 15 minutos y, mientras la aplicación está abierta, comprueba cada minuto si el TTL venció para iniciar una actualización asíncrona. Una actualización manual siempre evita la caché.

## Banner unificado con la ficha

Cada resultado de catálogo ahora usa el mismo orden de la ficha: portada 16:9, franja de identidad semitransparente dentro de la portada, icono de 50 píxeles, título, publisher, autor y estrellas verificadas. Una primera captura reveló que una regla de estilo del recurso remoto se propagaba a los rótulos internos; se restringió al objeto de imagen y la segunda captura confirma tipografía compacta y legible dentro del banner.

## Preferencias locales

Configuración expone controles para vista de inicio, tres densidades de cuadrícula, modo claro u oscuro y cinco colores de acento. La primera comprobación en modo claro confirmó la aplicación inmediata de tema y acento, pero se tomó antes de que la consulta pública terminara; la captura final de una cuadrícula personalizada debe esperar la carga del catálogo para ser válida.

La captura final espera la terminación de iconos y portadas: confirma modo claro con acento océano, vista compacta y cinco columnas de fichas. La densidad mantiene portadas, iconos y estrellas sin desbordamiento; la información secundaria se reduce de forma deliberada en esta densidad y se conserva completa en los modos de tres y cuatro columnas.

Los tres modos no son etiquetas decorativas: Compacto reduce márgenes, separación y sombra; Milimetrado usa espaciado intermedio y contornos más contenidos; MacOS Style conserva mayor respiración, separación y profundidad. La densidad elegida también determina la anchura de tarjeta disponible antes de resolver de forma adaptable las tres, cuatro o cinco columnas solicitadas.

## Ficha lateral y acciones de paquete

La ficha final reparte identidad, aviso y acciones de gestión a la izquierda, con el README desplazable en un panel separado a la derecha. El README mantiene selección de texto y el botón de copia traslada la selección al portapapeles. Las acciones visibles dependen del estado local comprobado: instalación disponible para paquetes ausentes; actualizar y desinstalar para paquetes instalados; y cancelar con barra indeterminada mientras una operación cooperativa está activa. La captura confirma contraste legible para el estado y la disposición lateral.

La comprobación de progreso muestra que el estado `Descargando y validando el release…`, la barra indeterminada y Cancelar sustituyen las acciones de mutación sin desplazar ni recortar el banner, el aviso o el README. Esta vista representa el estado visual de una operación activa; no se ejecutó ni se declaró completada ninguna instalación durante la captura.

## README Markdown

El panel lateral sustituye el editor de texto plano por un visor Markdown de Qt. La validación con encabezado, lista, cita y bloque de consola confirma la jerarquía visual y la selección para copiar. Los enlaces del README se limitan a `https` y `http`; los demás esquemas se bloquean. La captura integrada aplica el estilo raíz completo de Foundstore y confirma contraste suficiente bajo el tema oscuro, sin desplazar las acciones ni la cabecera de identidad.
