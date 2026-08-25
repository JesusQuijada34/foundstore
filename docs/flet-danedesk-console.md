# Foundstore Console Flet

## Propósito

Foundstore Console es una aplicación multiplataforma de escritorio para administrar DaneDesk, licencias y solicitudes de instalación desde una única superficie. Complementa la aplicación Qt6 de catálogo; no la reemplaza y no modifica el agente local de manera silenciosa.

La consola sólo muestra estados que el servidor haya confirmado. No inventa progreso, dispositivos, instalaciones, métricas ni inventario técnico. Las acciones de instalación y de inventario siguen requiriendo la aprobación local del DaneDesk.

## Navegación

| Área | Información y acciones permitidas |
|---|---|
| Resumen | Total de DaneDesk activos, licencias activas y solicitudes pendientes basadas en la respuesta de la API. |
| DaneDesk | Nombre, plataforma, conexión, estado de seguridad, versión declarada y detalle minimizado por propietario. Permite abrir el detalle, no cambiar MAC. |
| Licencias | Lista de licencias propias, creación explícita y revocación con confirmación textual. |
| Instalaciones | Búsqueda de catálogo y solicitud hacia un DaneDesk activo; muestra sólo los estados de eventos reales. |
| Privacidad E2E | Preparación de clave, transportes firmados y accesos a la consola web para descifrar informes mientras no exista un registro multi-clave de propietario. |

La interfaz usa una barra lateral adaptativa para escritorio y una navegación compacta en pantallas estrechas. Los controles críticos miden al menos 44 px, disponen de texto además de icono, foco visible y una confirmación antes de revocar o solicitar acciones sensibles.

## Autorización nativa propuesta

La sesión web de GitHub no se copiará a Flet y la aplicación no solicitará ni guardará tokens de GitHub. El contrato a añadir en la API Flask debe seguir un flujo de autorización por dispositivo:

1. La consola crea una solicitud efímera con PKCE y recibe una URL HTTPS de autorización.
2. La persona propietaria termina GitHub OAuth en el navegador predeterminado y confirma la vinculación de la consola.
3. La aplicación sondea exclusivamente el identificador efímero hasta recibir un token de consola limitado a su cuenta y con caducidad corta.
4. El token se guarda sólo en el almacén seguro del sistema operativo. Si no está disponible, la consola exige autorización nuevamente y no cae a un archivo legible.
5. Cada endpoint propietario valida el token de consola, la cuenta y el alcance. El token no permite acceso a otros propietarios, órdenes del agente ni operaciones administrativas globales.

El servidor debe aplicar límite de intentos, vencimiento, uso único y revocación. Los tokens de consola no sustituyen credenciales de agentes ni permiten cambiar o aleatorizar direcciones MAC.

## E2E y datos sensibles

La consola Flet no descifra por ahora los informes E2E que la consola web protege mediante una clave Web Crypto no exportable en IndexedDB. No se duplicará ni exportará esa clave. Flet mostrará el estado de preparación E2E y ofrecerá abrir la pantalla web protegida cuando haga falta revisar un informe cifrado.

Una fase futura podrá añadir múltiples claves públicas de propietario o un mecanismo de recuperación aprobado. Hasta entonces, cualquier inventario sensible permanece en el sobre cifrado y fuera de los paneles Flet.

## Estados y errores

Las vistas deben representar `loading`, `empty`, `offline`, `unauthorized`, `error` y `ready`. Una solicitud de instalación sólo aparecerá como `instalando` después de un evento firmado del agente; la creación de la solicitud se muestra como `pendiente de aprobación local`.

La revocación exige una advertencia y una frase de confirmación. Al finalizar, la consola actualiza la lista desde el servidor en lugar de asumir que el cambio se aplicó.
