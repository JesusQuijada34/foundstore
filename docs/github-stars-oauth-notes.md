# Notas de permisos GitHub para estrellas

Consultado el 21 de agosto de 2026.

GitHub expone el contador público de estrellas en los datos de repositorio y permite consultar, crear o retirar una estrella del usuario autenticado mediante `GET`, `PUT` y `DELETE /user/starred/{owner}/{repo}`. La creación o retirada cambia realmente el estado de la cuenta GitHub, por lo que Foundstore debe pedir consentimiento explícito inmediatamente antes de la acción y no conservar el token fuera de la sesión.

Para repositorios públicos, GitHub documenta que `public_repo` concede acceso de lectura/escritura a repositorios públicos y es el alcance requerido para poner estrella. El alcance `repo` da acceso mucho más amplio a repositorios públicos y privados, por lo que no se solicitará para el catálogo público ni para estrellas de repositorios públicos.

Fuentes:

- [REST API endpoints for starring](https://docs.github.com/en/rest/activity/starring#create-a-star-for-the-authenticated-user)
- [Scopes for OAuth apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps)
