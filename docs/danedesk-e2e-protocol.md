# Protocolo DaneDesk E2E v1

## Objetivo y límite explícito

Foundstore transportará mediante cifrado de extremo a extremo los **payloads técnicos sensibles** entre la consola web autenticada del propietario y un DaneDesk específico. El servidor conservará únicamente metadatos operativos mínimos: identificador opaco del dispositivo, época de clave, caducidad, tamaño aproximado, tipo genérico de sobre y marcas de recepción. El servidor seguirá verificando autorización, pertenencia, revocación y firma de transporte, pero no descifrará el contenido de los sobres.

Esta garantía no oculta que existe un DaneDesk vinculado, cuándo se conectó, ni que se entregó un comando. Tampoco convierte las métricas agregadas de instalaciones en privadas por sí mismas. Cada vista debe indicar qué dato es local/E2E, cuál es metadato operativo y cuál es agregado.

## Primitivas y versiones

La implementación v1 usará capacidades nativas de navegador y Python `cryptography` para evitar dependencias criptográficas hechas a medida:

| Función | Primitiva | Motivo |
| --- | --- | --- |
| Acuerdo de clave web ↔ DaneDesk | ECDH P-256 | Está disponible en Web Crypto y `cryptography`, permitiendo que la consola cifre antes de enviar el sobre. |
| Derivación de clave | HKDF-SHA-256 | Separa claves y liga la derivación al dispositivo, época, identificador de sobre y dirección. |
| Cifrado autenticado | AES-256-GCM | Confidencialidad e integridad de cada payload con nonce único de 96 bits. |
| Transporte y autorización | HTTPS + HMAC existente de comando + token de agente | Conserva autenticación de ruta y rechazo temprano antes del descifrado E2E. |

La elección P-256 permite usar Web Crypto directamente en la consola. X25519 sigue siendo una alternativa aceptable para clientes nativos, pero no se mezclará dentro de la versión 1 del mismo protocolo. La documentación de `cryptography` recomienda pasar secretos ECDH por una KDF y rotar la clave efímera en cada intercambio. [1] El modo AES-GCM protege confidencialidad e integridad del mensaje asociado al nonce, no sólo su confidencialidad. [2]

## Identidades y claves

Cada DaneDesk genera localmente una pareja P-256 de cifrado durante una migración confirmada. La clave privada nunca se envía y se guarda junto al estado del agente con permisos `0600`; el servidor registra sólo la clave pública JWK, un `keyEpoch`, una huella y la fecha de alta. La consola del propietario generará una clave de control P-256 no exportable en el navegador y publicará únicamente su JWK cuando exista una política de persistencia y recuperación explícita; esa consola todavía no está implementada.

La rotación de una clave de dispositivo exige token de agente válido y prueba de posesión de la clave actual o una aprobación de propietario que invalida los sobres pendientes. La rotación de clave de control se inicia desde una sesión GitHub del propietario y deja los sobres históricos sin descifrar a propósito; no existe una puerta trasera de recuperación en el servidor.

## Sobre de comando

La consola descarga la clave pública del DaneDesk desde una ruta protegida, genera una clave efímera por comando y deriva una clave AES mediante HKDF. Cifra el payload localmente y entrega al servidor el siguiente sobre versionado:

```json
{
  "version": 1,
  "deviceId": "opaco",
  "keyEpoch": 1,
  "envelopeId": "único",
  "expiresAt": "ISO-8601",
  "senderEphemeralPublicJwk": { "kty": "EC", "crv": "P-256" },
  "nonce": "base64url-96-bit",
  "ciphertext": "base64url",
  "aad": "base64url"
}
```

El AAD canónico liga `version`, `deviceId`, `keyEpoch`, `envelopeId`, `expiresAt` y dirección `owner-to-device`. El servidor valida tamaño, estructura, caducidad, AAD y época; guarda sólo el sobre opaco y emite un comando de transporte firmado que contiene el identificador y la época. Los sobres tienen identificador único, recibo único y quedan inaccesibles después de una rotación de época. El agente deberá verificar primero la firma HMAC, caducidad y no repetición, y sólo después descifrar. Un fallo de autenticación, época o AAD se registra como error genérico sin guardar plaintext.

## Estado de implementación

| Componente | Estado | Límite |
| --- | --- | --- |
| Registro de clave pública P-256 y huella por DaneDesk | Implementado | La clave privada sigue local; no se registra material privado. |
| Sobre `owner-to-device` opaco v1, AAD, tamaño, caducidad, epoch y replay | Implementado en el servidor | El servidor enruta y registra recibos; no descifra. |
| Despacho por comando HMAC con `envelopeId` y `keyEpoch` | Implementado en el servidor | Requiere que el agente actualizado lo procese. |
| Consola Web Crypto de propietario y clave no exportable | Pendiente | Falta definir persistencia/recuperación segura antes de exponerla. |
| Descifrado local del agente y aprobación local de inventario | Implementado en la rama fuente del agente | No se publica una release hasta validar integración y recibir autorización. |
| Sobres `device-to-owner` para inventario sensible | Implementado en servidor y rama fuente del agente | El servidor almacena sólo ciphertext; falta la consola Web Crypto del propietario para descifrarlo visualmente. |

Las acciones de instalación, bloqueo, timbre y renovación de configuración mantienen aprobación local. El agente nunca acepta que el servidor o la consola conviertan un sobre válido en una instalación automática.

## Telemetría y detalle del dispositivo

El agente enviará un sobre E2E de `device-to-owner` únicamente tras el primer vínculo o una solicitud localmente aprobada. Incluirá nombre declarado, plataforma, versión del agente, estado de bloqueo, capacidades, lista resumida de servicios declarados, estado de instalación y, si el propietario lo solicita, la identidad de red. Foundstore no almacenará un MAC en texto claro: dentro del payload E2E puede mostrarse al propietario como detalle sensible; las vistas agregadas usarán una huella truncada.

No se implementará una orden para cambiar o aleatorizar la dirección MAC. El panel podrá solicitar una **reinscripción de red** o una actualización de inventario con aprobación local, pero no alterará la identidad de red de un equipo. Esta separación evita que una herramienta de administración se convierta en un mecanismo de evasión de controles de red.

## Progreso de instalación y catálogo

Los estados `awaiting_local_approval`, `installing`, `completed` y `failed` se emiten como sobres E2E. De forma separada, el agente publica un recibo agregado y minimizado para actualizar un contador por paquete y dispositivo, sin publicar la lista de instalaciones de una persona. La interfaz muestra una barra marquee sólo mientras existe un estado `installing` reciente de un DaneDesk conectado; si el agente no informa progreso, la interfaz muestra “esperando confirmación local”, no un porcentaje inventado.

## Migración y compatibilidad

Los agentes anteriores continúan en modo de compatibilidad: sólo reciben comandos HMAC existentes y no muestran detalle sensible E2E. La consola marcará el equipo como “actualización de seguridad disponible”, sin bloquearlo ni enviarle datos nuevos. El nuevo agente debe completar pruebas de migración, revocación, decriptado, replay y autorización local antes de empaquetarse. La publicación de una nueva release requiere autorización explícita del propietario.

## Referencias

[1] [Documentación oficial de ECDH y KDF, `cryptography`](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ec/)

[2] [Documentación oficial de AESGCM, `cryptography`](https://cryptography.io/en/latest/hazmat/primitives/aead/)
