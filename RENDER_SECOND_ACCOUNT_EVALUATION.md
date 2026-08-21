# Evaluación: segunda cuenta Render para Foundstore

## Conclusión

Una segunda cuenta Render puede desplegar técnicamente la rama `render` de `JesusQuijada34/foundstore` siempre que esa cuenta autorice Render para acceder al repositorio. Sin embargo, **no puede sustituir de forma transparente a la instancia actual**: cada servicio web recibe un subdominio `onrender.com` único y la URL canónica actual, `https://imfoundstore.onrender.com`, no debe ser usada simultáneamente por dos servicios.[1]

La opción segura es utilizar el segundo servicio como **staging, recuperación controlada o preproducción**, con una URL diferente. Mantener ambas instancias sirviendo producción sobre el mismo estado sin una estrategia de conmutación puede producir despliegues desalineados y resultados difíciles de auditar.

| Área | Resultado | Decisión o control requerido |
|---|---|---|
| Repositorio GitHub | Viable | La segunda cuenta debe conectar GitHub y tener acceso a `JesusQuijada34/foundstore`; Render permite elegir cualquier repositorio al que la identidad conectada tenga acceso.[2] |
| URL `onrender.com` | No reutilizable | Elegir un nombre de servicio distinto, por ejemplo `foundstore-staging`, y por tanto una URL distinta. Conservar `imfoundstore.onrender.com` como origen canónico mientras el primer servicio siga activo.[1] |
| Dominio personalizado | Requiere conmutación explícita | Un dominio puede apuntar a un servicio a la vez. Para migrar el origen canónico, primero verificar salud, después reasignar dominio/OAuth y retirar el servicio anterior. |
| GitHub OAuth | Riesgo de callback | La app OAuth actual tiene callback canónico `https://imfoundstore.onrender.com/auth/github/callback`. Para staging, usar una segunda GitHub OAuth App o no activar el inicio de sesión; no cambiar el callback de producción durante pruebas. |
| Variables y secretos | Aislados por servicio | Cargar por separado `MONGO_URI`, `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` y `NULL_HV`; las variables se gestionan por servicio y los grupos de entorno deben evitar colisiones.[3] |
| Datos | MongoDB compartido sólo con control | Para una prueba sin efectos, usar una base MongoDB distinta. Para una migración planificada, usar el mismo `MONGO_URI` sólo después de comprobar esquema, proteger el acceso y evitar dos versiones incompatibles escribiendo al mismo tiempo. El fallback SQLite no es una opción de producción compartida. |

## Procedimiento seguro propuesto

1. Conectar la segunda cuenta Render a GitHub y confirmar el acceso de la GitHub App al repositorio `JesusQuijada34/foundstore`.[2]
2. Crear un Web Service desde la rama `render`, raíz del repositorio, con el inicio `python app.py` y un nombre de servicio nuevo.
3. Configurar **valores propios por servicio**. Para staging, usar una base MongoDB aislada y una GitHub OAuth App de staging, o desactivar el acceso OAuth de prueba.
4. Verificar `/healthz`, `/api/v1/catalog`, el manifiesto PWA y las rutas de licencia antes de exponer usuarios al servicio alterno.
5. Si se decide migrar producción, completar una ventana de cambio: congelar despliegues, verificar que ambos servicios usen una versión compatible, mover el dominio/callback de OAuth una sola vez y retirar el servicio anterior tras confirmar telemetría y persistencia.

> El segundo servicio es **viable como entorno aislado**, no como réplica activa sin una operación de conmutación y datos explícitamente gobernados.

## Referencias

[1]: https://render.com/docs/web-services "Render Docs: Web Services"
[2]: https://render.com/docs/github "Render Docs: Connect GitHub"
[3]: https://render.com/docs/configure-environment-variables "Render Docs: Environment Variables and Secrets"
