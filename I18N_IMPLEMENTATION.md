# Internacionalización de Foundstore

## Decisiones

- La preferencia explícita del usuario (`?lang=` o cookie) tiene prioridad sobre la detección automática.
- La detección automática usa `CF-IPCountry` cuando Render/proxy lo proporciona y, como respaldo opcional, una consulta cacheada a `ipwho.is`.
- `Accept-Language` funciona como segundo respaldo y español como último fallback.
- Se conservará la preferencia durante 365 días y se expondrán `current_locale`, `available_locales` y `t` a todas las plantillas.
- La selección manual debe ser accesible, visible en el layout compartido y no depender únicamente de iconos o banderas.
- Los locales se normalizan a etiquetas BCP 47 y los códigos de país se mapean a locales regionales; los países sin una traducción específica usan el idioma de respaldo configurado.

## Cobertura inicial

El catálogo tendrá locales regionales para español, inglés, francés, alemán, portugués, italiano, neerlandés, catalán, japonés, coreano, chino simplificado, ruso, árabe, hindi, turco, polaco y ucraniano. La arquitectura acepta cualquier locale BCP 47 adicional y evita romperse ante países o idiomas no traducidos.

## Orden de resolución

1. Parámetro `lang` válido.
2. Cookie `foundstore_locale` válida.
3. Sesión autenticada si en el futuro almacena una preferencia.
4. País detectado por proxy/IP.
5. Cabecera `Accept-Language`.
6. `es` como fallback de la interfaz existente.
