# Validación visual de Foundstore Qt6

## Ejecuciones bajo Xvfb

La primera ejecución confirmó que la ventana arrancaba, pero el titular y la marca heredaban un color oscuro contra un fondo oscuro y el catálogo bloqueaba la interfaz durante la consulta. La segunda ejecución corrigió la legibilidad del encabezado y dejó visible un estado de carga mientras el catálogo se consulta en un hilo Qt separado.

## Próxima validación

La captura posterior debe realizarse después de recibir el catálogo o mediante una fuente de datos de prueba explícita de la propia aplicación. Se debe comprobar la geometría de las filas de resultados, el acceso a la ficha y la confirmación antes de cualquier instalación.

## Catálogo y ficha cargados

El catálogo real completó la consulta y mostró 27 paquetes verificados en filas compactas, con búsqueda, acciones de ficha e instalación y navegación lateral. La navegación a la ficha funciona, pero la captura reveló que `detailTitle` heredaba color oscuro sobre el panel oscuro. Antes de la entrega se debe aplicar un color explícito de alto contraste al título de detalle y tomar una nueva captura de cierre.

## Integración API pública

La aplicación reemplazó el lector directo de `repo.list` para navegación por la API pública de Foundstore. La captura de catálogo confirma nueve paquetes que ya pasan el contrato web, iconos remotos y estrellas GitHub verificadas; por ejemplo, Camera Selfie expone 2 estrellas. La ficha posterior confirma icono, portada 16:9, README y el mismo conteo verificado desde `GET /api/v1/catalog/camera`. La instalación permanece separada y conserva la confirmación local antes de usar el gestor Fluthin.
