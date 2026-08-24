# Foundstore: incorporación web-first y experiencia de cuenta

## Decisiones de alcance

La primera entrega es **web-first**. Foundstore permite descubrir paquetes, iniciar sesión con GitHub y administrar licencias desde el navegador. El agente sólo se ofrece cuando una persona intenta enviar una instalación a un dispositivo compatible; el sitio no descarga ni ejecuta paquetes automáticamente por visitar una página.

El serial visible en la cuenta es una **licencia de vínculo**, no una contraseña de sesión. Sólo puede iniciar un vínculo de duración limitada y requiere que el propietario autenticado confirme el código mostrado por el equipo. La autorización del agente y la ejecución de paquetes continúan separadas: el agente valida su orden firmada y exige la confirmación local `INSTALAR` antes de invocar `flut`.

| Superficie | Propósito | Regla de seguridad |
|---|---|---|
| Cuenta Foundstore | Entrada GitHub, avatar, accesos de cuenta y salida | La sesión web usa OAuth; nunca se deriva de una licencia. |
| Licencias | Mostrar, copiar y crear seriales de vínculo | La licencia se muestra únicamente al propietario autenticado. |
| Dispositivos | Explicar estado y ofrecer incorporación del agente | Sólo se muestran dispositivos asociados a la cuenta. |
| Incorporación | Instrucción `curl` por plataforma compatible o ruta gráfica | Los scripts verifican origen e integridad; no instalan paquetes de catálogo. |
| Perfil público | Identidad del creador y paquetes verificados | Respeta privacidad del avatar, biografía, inventario y contadores. |

## Experiencia de interfaz

La cabecera autenticada usa un avatar con un menú de cuenta accesible por clic, teclado y hover cuando el dispositivo lo admite. El menú contiene Perfil, Configuración, Licencias, Dispositivos y Cerrar sesión. En móvil se abre desde el mismo control, sin depender de hover.

La configuración se organiza en secciones de Cuenta, Privacidad, Licencias y Dispositivos. La vista pública de creador adopta una composición original de perfil de contenido: cabecera compacta, métricas reales y una tira vertical de tarjetas que prioriza la portada `portrait` oficial con icono, nombre, editor y compatibilidad. No replica la interfaz ni recursos de terceros.

## Criterios de aceptación

- Las acciones de cuenta son operables con teclado y lectores de pantalla, con foco visible y objetivos táctiles de al menos 44 px.
- Los menús y transiciones respetan `prefers-reduced-motion` y `prefers-reduced-transparency`.
- Los controles no usan emoji como iconos estructurales y los retratos de paquete reservan relación de aspecto para evitar saltos de diseño.
- Ninguna API devuelve un token del agente ni habilita instalación remota sin propietario autenticado, dispositivo compatible y aprobación local del agente.

## Comprobación visual local

La portada pública se verificó en el servidor Flask local: mantiene la laptop demostrativa, el logotipo y las llamadas a GitHub sin exponer catálogo privado. La ruta `/settings` respondió con el muro de GitHub para una sesión anónima; por ello las superficies de seriales, dispositivos y preferencias no se entregan antes de la autenticación.
