# Foundstore Flask para Render

La rama `render` aísla este servicio Flask de la aplicación React/tRPC que permanece en `main`. En esta rama, `app.py`, `maintenance.py`, `requirements.txt`, `test_app.py`, `render.yaml` y `render_templates/` viven en la raíz. Render debe desplegar desde la raíz con `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 45 app:app`.

El servicio responde directamente en `/`; no existen redirecciones de aplicación. Render puede redirigir HTTP a HTTPS, lo cual es una protección de transporte del proveedor y no una redirección de Foundstore.

## Servicio central compartido

Cloud Danenone Devices es la fuente de estado compartida. Foundstore consulta `GET /api/v1/devices` y mantiene una espera larga contra `GET /api/v1/devices/<id>/events/next`; el agente local usa la misma identidad DaneDesk, recibe órdenes en `commands/next` y devuelve eventos en `POST .../events`. Cada parte tiene una credencial distinta: la app operativa usa la credencial de propietario del servidor y el agente usa un token propio del DaneDesk, emitido una única vez al consumir el pairing.

El servicio entrega además una firma HMAC por orden. Render mantiene `COMMAND_SIGNING_KEY` como secreto de servidor y deriva una clave exclusiva para cada DaneDesk al emparejarlo. El agente verifica `id`, `deviceId`, tipo, carga útil y vencimiento antes de almacenar una orden. Esto detecta una modificación en tránsito; no sustituye la protección de un equipo que ya ha sido comprometido localmente.

Una instalación desde Foundstore se convierte en una orden `install_request`. El servidor entrega la solicitud, pero no instala nada: el agente debe mostrar y registrar la aprobación local antes de ejecutar `flut`. Después puede emitir `install.awaiting_approval`, `install.approved`, `install.rejected`, `install.completed` o `install.failed` para actualizar el estado de la tienda.

## Almacenamiento

Si `MONGODB_URI` está configurada y responde, MongoDB guarda los códigos de pairing, dispositivos y órdenes de corta vigencia. Si no hay URI o MongoDB no está disponible, Flask usa SQLite en `DATA_DIR`, que por defecto es `./var`. La ruta no presupone un volumen en `/var/data`: sólo se debe definir `DATA_DIR` para una ubicación persistente cuando el proveedor haya montado y autorizado explícitamente ese volumen. En Render Free, el respaldo SQLite es efímero y no debe tratarse como almacenamiento durable.

La rama acepta los nombres actuales `MONGODB_URI`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` y `FLASK_SECRET_KEY`. Durante la transición también reconoce `MONGO_URI`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` y `SECRET_KEY`; las instalaciones nuevas deben utilizar los nombres actuales.

La GitHub OAuth App debe registrar exactamente este callback:

```text
https://imfoundstore.onrender.com/auth/github/callback
```

El callback heredado `/login/github/authorized` pertenece a la aplicación anterior y no completa el vínculo de licencia de esta rama Flask.

Los trabajos cron no tienen acceso a discos persistentes. Por ello, `foundstore-maintenance` usa MongoDB para eliminar códigos de pairing y órdenes caducadas. Si se escoge solo SQLite, la limpieza ocurre al reiniciar o se debe ejecutar como una acción interna del servicio web.

## Flujo DaneDesk

`POST /api/v1/pairing-codes` crea un código alfanumérico de ocho caracteres y una URI `foundstore://` que contiene ese código, no un token persistente. La creación exige `X-Foundstore-Owner-Token`. `POST /api/v1/agent/bootstrap` consume el código una sola vez y entrega el token del agente por el cuerpo HTTPS.

El agente solicita `GET /api/v1/devices/<id>/commands/next?wait=25` con `X-Danenone-Agent-Token`. La espera máxima es de 25 segundos, tras la cual el agente aplica retroceso antes de volver a conectar. La ubicación se acepta únicamente de un agente autenticado y se conserva únicamente cuando el dispositivo está en estado `lost` y tiene protección de ubicación activa.

El endpoint de restauración devuelve solo `approvedApps` previamente incluidas al pairing. Debe seguir existiendo aprobación local antes de ejecutar `flut`.
