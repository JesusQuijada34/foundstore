# Foundstore v1.1-26.08-22.31

Release de **Foundstore Fluthin Store** para `Danenone`, con publisher `Influent`, author `JesusQuijada34` y plataforma de proyecto `AlphaCube` compilada para el asset Linux/Danenone.

Incluye el catálogo GitHub, búsqueda de paquetes, instalación y actualización mediante `flut`, registro FreeDesktop, integración de autostart y soporte para paquetes Fluthin con varios binarios. El launcher prioriza el ejecutable cuyo nombre coincide con el app id y evita elegir por error los auxiliares `flut` o `fluthin_manager`.

El artefacto fue compilado con PackageMaker después de corregir la acumulación de binarios multi-script y las colisiones con carpetas estructurales como `app` y `config`. Fue validado como ZIP seguro, con `details.xml`, icono y binarios requeridos. El workflow CI se conserva localmente hasta disponer del permiso GitHub `workflow`; esto no afecta al código ni al asset publicado.
