# foundstore

## Arquitectura de la Aplicación

`foundstore` es una tienda virtual construida con Flask, diseñada para alojar paquetes `iflapp` y proporcionar perfiles dinámicos para desarrolladores. La aplicación integra autenticación a través de GitHub OAuth y gestiona cuentas de desarrolladores 'ondev' con una base de datos local.

### Estructura del Proyecto

```
foundstore/
├── app.py                  # Aplicación principal Flask
├── config.py               # Configuración de la aplicación (claves API, secretos, etc.)
├── models.py               # Definición de modelos de datos (usuarios, cuentas ondev, paquetes)
├── routes.py               # Definición de todas las rutas de la aplicación
├── services.py             # Lógica para interacción con la API de GitHub y operaciones de base de datos
├── templates/              # Plantillas Jinja2 para la interfaz de usuario
│   ├── base.html           # Plantilla base para todas las páginas
│   ├── index.html          # Página de inicio
│   ├── login.html          # Página de inicio de sesión con GitHub
│   ├── developer_profile.html # Plantilla para perfiles de desarrolladores (/<github_username>/)
│   ├── package_detail.html # Plantilla para detalles de paquetes (/packages/<package_name>/)
│   ├── ondev_panel.html    # Panel profesional para cuentas 'ondev'
│   └── error.html          # Página de error genérica
├── static/                 # Archivos estáticos (CSS, JavaScript, imágenes)
│   ├── css/                # Hojas de estilo CSS
│   ├── js/                 # Archivos JavaScript
│   └── img/                # Imágenes y otros activos visuales
├── data/
│   └── ondev_accounts.list # Base de datos local para cuentas 'ondev' (formato JSONL)
├── requirements.txt        # Dependencias de Python
├── render.yaml             # Configuración de despliegue para Render
└── Procfile                # Punto de entrada para Gunicorn en Render
```

### Características Clave

1.  **Aplicación Flask:** El núcleo de la aplicación web se construirá utilizando el microframework Flask, proporcionando una estructura ligera y flexible.

2.  **Autenticación GitHub OAuth:** Los usuarios iniciarán sesión en la plataforma utilizando sus cuentas de GitHub, lo que simplificará el proceso de registro y autenticación.

3.  **Cuentas "ondev":**
    *   Un archivo local `.list` (en formato JSONL) actuará como una base de datos para almacenar información de las cuentas "ondev".
    *   Los usuarios con cuentas "ondev" tendrán acceso a un panel profesional con funcionalidades adicionales.
    *   La aplicación generará y modificará rutas dinámicamente para perfiles de desarrolladores, siguiendo el patrón `/<GitHubusername>/repo/`.
    *   Se implementará una plantilla específica para la sección "Hero" de cada perfil de desarrollador.

4.  **Catálogo de Paquetes:**
    *   Se creará un catálogo de paquetes personalizado dentro de la tienda, reemplazando cualquier catálogo de repositorio preexistente.
    *   Las rutas dinámicas para los paquetes seguirán el patrón `/packages/<package_name>/`.
    *   Se diseñarán plantillas específicas para cada paquete `iflapp`.

5.  **Plantilla de Perfil de Desarrollador:**
    *   Si un usuario de GitHub autenticado posee un repositorio llamado `ismyself`, la estructura JSON de este repositorio se utilizará para poblar dinámicamente la plantilla de su perfil de desarrollador. Esto incluirá la descripción del creador, banner, logo (foto de perfil de GitHub), enlaces a redes sociales o Linktree, etc.

6.  **Despliegue en Render:** La aplicación estará configurada para un despliegue sencillo y eficiente en la plataforma Render, utilizando `render.yaml` y `Procfile`.

### Flujo de Trabajo de Autenticación y Perfiles

1.  **Inicio de Sesión:** El usuario inicia sesión a través de GitHub OAuth.
2.  **Verificación "ondev":** Tras el inicio de sesión, la aplicación verifica si el usuario tiene una cuenta "ondev" registrada en `ondev_accounts.list`.
3.  **Creación de Perfil Dinámico:**
    *   Si el usuario tiene un repositorio `ismyself` en GitHub con la estructura JSON esperada, esta información se utiliza para renderizar su perfil de desarrollador en la ruta `/<GitHubusername>/`.
    *   Si el usuario es "ondev", se le otorga acceso al panel profesional.

### Base de Datos Local (`ondev_accounts.list`)

Este archivo almacenará información de las cuentas "ondev" en formato JSONL (JSON Lines), donde cada línea es un objeto JSON que representa una cuenta. Ejemplo:

```json
{"github_username": "jesusquijada34", "is_ondev": true, "packages": ["package1", "package2"]}
{"github_username": "otro_dev", "is_ondev": true, "packages": ["package_x"]}
```

Esta estructura permitirá a la aplicación leer y escribir fácilmente los datos de las cuentas "ondev".
