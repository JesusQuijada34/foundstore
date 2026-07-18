# Configuración de GitHub OAuth para Foundstore

## Problema Identificado

El error `"The redirect_uri is not associated with this application"` ocurre cuando la URL de redirección que GitHub recibe no coincide exactamente con la registrada en la configuración de tu aplicación OAuth en GitHub.

## Solución Implementada

Se ha modificado la aplicación para permitir configurar explícitamente la `redirect_uri` mediante una variable de entorno `GITHUB_OAUTH_REDIRECT_URI`.

### Pasos para Configurar

#### 1. Registrar tu Aplicación OAuth en GitHub

1. Ve a https://github.com/settings/developers
2. Haz clic en "New OAuth App"
3. Completa el formulario:
   - **Application name**: Foundstore
   - **Homepage URL**: https://tu-dominio.com (o http://localhost:8000 para desarrollo local)
   - **Authorization callback URL**: Esta es la URL de redirección que GitHub usará

#### 2. Configurar la URL de Redirección

Dependiendo de tu entorno:

**Para desarrollo local con exposición pública:**
```bash
GITHUB_OAUTH_REDIRECT_URI=https://8000-i7rjhdpvks8lcxvrzyg7e-e5a3509a.us2.manus.computer/login/github/authorized
```

**Para producción en Render:**
```bash
GITHUB_OAUTH_REDIRECT_URI=https://foundstore.onrender.com/login/github/authorized
```

**Para desarrollo local sin exposición pública:**
```bash
GITHUB_OAUTH_REDIRECT_URI=http://localhost:8000/login/github/authorized
```

#### 3. Actualizar Variables de Entorno

En tu archivo `.env` o en la configuración de tu plataforma de hosting (Render, Heroku, etc.):

```env
GITHUB_OAUTH_CLIENT_ID=tu_client_id_aqui
GITHUB_OAUTH_CLIENT_SECRET=tu_client_secret_aqui
GITHUB_OAUTH_REDIRECT_URI=https://tu-dominio.com/login/github/authorized
```

#### 4. Registrar la URL en GitHub

1. Ve a https://github.com/settings/developers
2. Selecciona tu aplicación OAuth
3. En "Authorization callback URL", ingresa exactamente la misma URL que configuraste en `GITHUB_OAUTH_REDIRECT_URI`
4. Haz clic en "Update application"

## Cómo Funciona

1. Cuando el usuario hace clic en "Login with GitHub", se redirige a:
   ```
   https://github.com/login/oauth/authorize?response_type=code&client_id=...&redirect_uri=...
   ```

2. Después de que el usuario autoriza, GitHub redirige a la `redirect_uri` con un código:
   ```
   https://tu-dominio.com/login/github/authorized?code=...&state=...
   ```

3. La aplicación Flask-Dance captura este código y lo intercambia por un token de acceso

## Solución de Problemas

### Error: "The redirect_uri is not associated with this application"

**Causa**: La URL de redirección no coincide con la registrada en GitHub

**Solución**:
1. Verifica que `GITHUB_OAUTH_REDIRECT_URI` esté correctamente configurada
2. Verifica que la URL en GitHub coincida exactamente (incluyendo protocolo, dominio, puerto y ruta)
3. No incluyas parámetros de query en la URL de redirección

### Error: "Invalid request: redirect_uri mismatch"

**Causa**: Similar al anterior

**Solución**: Asegúrate de que la URL sea exacta, incluyendo:
- Protocolo (http:// o https://)
- Dominio exacto
- Ruta exacta (/login/github/authorized)

## Desarrollo Local con Exposición Pública

Para probar localmente con una URL pública:

```bash
# 1. Exponer el puerto 8000
# (Ya está hecho automáticamente en Manus)

# 2. Configurar la variable de entorno
export GITHUB_OAUTH_REDIRECT_URI=https://8000-i7rjhdpvks8lcxvrzyg7e-e5a3509a.us2.manus.computer/login/github/authorized

# 3. Registrar esta URL en GitHub
# Ve a https://github.com/settings/developers y actualiza la URL de callback

# 4. Iniciar la aplicación
python3 app.py
```

## Despliegue en Render

1. Crea una nueva aplicación en Render
2. Conecta tu repositorio de GitHub
3. En "Environment Variables", añade:
   ```
   GITHUB_OAUTH_CLIENT_ID=tu_client_id
   GITHUB_OAUTH_CLIENT_SECRET=tu_client_secret
   GITHUB_OAUTH_REDIRECT_URI=https://foundstore.onrender.com/login/github/authorized
   ```
4. Render generará automáticamente la URL de tu aplicación (ej: foundstore.onrender.com)
5. Actualiza la URL de callback en GitHub con la URL de Render

## Notas Importantes

- **ProxyFix**: La aplicación usa `ProxyFix` para entender que está detrás de un proxy (en Render)
- **HTTPS**: En producción, siempre usa HTTPS
- **OAUTHLIB_INSECURE_TRANSPORT**: Está configurado para permitir HTTP en desarrollo, pero se recomienda usar HTTPS en producción
