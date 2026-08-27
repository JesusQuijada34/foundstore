# FoundStore

**Identidad del paquete:** `Influent.foundstore.v1.2-26.08-22.20`
**Autor:** `JesusQuijada34`
**Plataforma:** `AlphaCube`
**Descripción:** Tienda Fluthin para Danenone con catálogo GitHub, actualizaciones y gestor flut.

## Estructura PackageMaker 3.2.7

Este repositorio fue normalizado mediante **MoonFix**, usando la estructura de PackageMaker 3.2.7. El paquete público debe conservar `details.xml`, `version.res`, `autorun`, `autorun.bat`, `.storedetail`, `updater.py`, `config/settings.json`, los marcadores `.container` y los archivos de documentación correspondientes. El publisher oficial es `Influent` en los metadatos; el formateador de Packagemaker puede normalizar nombres de artefacto según su implementación vigente.

## Instalación y ejecución

Instala las dependencias declaradas en `lib/requirements.txt` cuando exista y ejecuta el entrypoint real del proyecto. En Linux, los comandos privilegiados son específicos de Danenone y no deben trasladarse a Windows. En proyectos AlphaCube, la validación Windows debe realizarse con el `buildthis` oficial de PackageMaker.

## Validación

La fuente debe pasar compilación sintáctica, pruebas funcionales disponibles, comprobación de identidad XML, protección contra traversal en ZIP y llamadas seguras a subprocess. Los artefactos `.iflapp` deben ser generados por PackageMaker; los paquetes Debian deben usar el nombre canónico `Influent.foundstore.v1.2-26.08-22.20_ARCH.deb`.

## Release

El tag y el título del release de esta iteración deben ser exactamente `v1.2-26.08-22.20`. Los assets deben usar el nombre canónico del paquete y una extensión objetiva. No se permite publicar un release AlphaCube que contenga únicamente el build Linux.

## Referencia original

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


## Cliente Fluthin para Danenone

Esta rama incluye una aplicación de escritorio `foundstore.py` basada en PyQt6 y Leviathan UI, además del gestor de línea de comandos `flut.py`. La aplicación examina `JesusQuijada34/catalog`, lee `details.xml` de cada repositorio, consulta los releases de GitHub y permite instalar paquetes `.iflapp` compatibles con la plataforma actual.

El gestor utiliza referencias con el formato `author/package`:

```bash
python flut.py catalog --refresh
python flut.py search settings
python flut.py install JesusQuijada34/leviathan-ui
python flut.py upgrade
python flut.py downgrade JesusQuijada34/leviathan-ui v1.0-26.08-21.56
python flut.py uninstall JesusQuijada34/leviathan-ui
python flut.py check-updates
```

Los paquetes instalados se registran bajo el estado de Danenone y generan una entrada FreeDesktop en `~/.local/share/applications`. El gestor valida `details.xml`, comprueba que el artefacto sea un ZIP válido, bloquea path traversal durante la extracción y registra notificaciones de instalación y actualización en el estado local.

La compilación multiplataforma se declara en `.github/workflows/build-fluthin.yml`. El workflow valida el contrato, instala Leviathan UI y solicita a Packagemaker la generación de los objetivos `Danenone` y `Knosthalij`. La publicación de un release requiere validar previamente cada asset `.iflapp` y usar la versión exacta de `details.xml`.
