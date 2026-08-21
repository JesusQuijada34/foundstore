# Vínculo de licencia y agente Foundstore

## Propósito

Foundstore trata el código de emparejamiento como una **licencia de dispositivo persistente**, no como una contraseña de GitHub ni como un token de agente. La persona propietaria debe iniciar sesión y autorizar la asociación antes de que un DaneDesk pueda recibir órdenes, instalar solicitudes aprobadas o consultar su identidad cloud.

## Estados

| Estado | Significado | Agente permitido |
|---|---|---|
| `issued` | La licencia fue emitida para una cuenta y aún no está vinculada a un dispositivo. | Puede iniciar una solicitud de vínculo, pero no recibe credenciales. |
| `awaiting_owner` | El equipo presentó la licencia y espera que la persona propietaria inicie sesión y la confirme en Foundstore. | Sólo puede consultar el estado de su propia solicitud efímera. |
| `active` | La persona autenticada confirmó el dispositivo y el servidor emitió una credencial exclusiva del agente. | Puede usar las rutas autenticadas de DaneDesk. |
| `revoked` | La licencia o el dispositivo fue revocado por robo, transferencia, recuperación o una señal de uso indebido revisada. | No puede consultar órdenes ni renovar credenciales; debe mostrar la pantalla de nuevo vínculo. |

## Flujo de activación

1. El agente recibe una licencia alfanumérica persistente y crea una solicitud de vínculo de corta vida.
2. El agente abre o muestra `verificationUri` y un código visible de confirmación. No recibe un token de GitHub.
3. La persona inicia sesión en GitHub dentro de Foundstore y confirma que el DaneDesk mostrado le pertenece.
4. Sólo entonces el agente canjea la solicitud una vez y recibe una credencial exclusiva del dispositivo con permisos locales `0600`.
5. La licencia queda asociada al dispositivo. Una nueva computadora requiere una licencia nueva o una transferencia aprobada explícitamente por el propietario.

## Revocación y recuperación

Cuando el servidor responde que la credencial está revocada, el agente borra las credenciales operativas, conserva únicamente un registro local de que debe re-vincularse y muestra una pantalla de **Vínculo requerido**. Esta pantalla nunca solicita una contraseña de GitHub: solicita una nueva licencia emitida por el propietario tras la recuperación o transferencia verificadas.

La revocación no debe dispararse por un fallo de red ni por un error transitorio. Los motivos aceptados son una acción explícita del propietario, un reporte de robo confirmado, una transferencia de dispositivo o una señal de uso indebido registrada que haya sido revisada. Cada cambio genera un evento de auditoría.

## Límites de seguridad

El código de licencia no se envía como encabezado de autenticación, no se registra, no se inserta en URI públicas y no se convierte en una sesión de GitHub. Las rutas públicas de catálogo y salud permanecen sin inicio de sesión. Las rutas de vínculo están limitadas a la solicitud efímera correspondiente; las rutas de órdenes y estado del dispositivo exigen la credencial de agente emitida después de la confirmación.
