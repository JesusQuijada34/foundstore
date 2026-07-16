# Servidor de Desarrollo Local

## Inicio Rápido

Para visualizar la página mientras la editas:

```bash
python server.py
```

Luego abre tu navegador en: **http://localhost:8000**

## Características

- ✅ Servidor HTTP simple en el puerto 8000
- ✅ Recarga manual (F5) para ver cambios
- ✅ CORS habilitado para desarrollo
- ✅ Sin caché para ver cambios inmediatamente

## Detener el Servidor

Presiona `Ctrl+C` en la terminal donde está corriendo el servidor.

## Solución de Problemas

Si el puerto 8000 está ocupado, puedes:
1. Cerrar otros servidores que estén corriendo
2. Modificar la variable `PORT` en `server.py` a otro número (ej: 8080, 3000, etc.)

## Edición en Vivo

1. Deja el servidor corriendo
2. Edita `index.html` en tu editor
3. Guarda los cambios
4. Recarga la página en el navegador (F5)
