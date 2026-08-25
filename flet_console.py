"""Foundstore Console: administración multiplataforma de licencias y DaneDesk."""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import flet as ft
import flet_secure_storage as fss

from flet_console_api import ConsoleApiError, FoundstoreConsoleApi


TOKEN_KEY = "foundstore.console.token"


class FoundstoreConsole:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.api = FoundstoreConsoleApi()
        self.storage = fss.SecureStorage()
        self.account = ""
        self.devices: list[dict[str, Any]] = []
        self.licenses: list[dict[str, Any]] = []
        self.packages: list[dict[str, Any]] = []
        self.device_id_field = ft.TextField(label="ID de DaneDesk", hint_text="Copia el identificador desde la lista", width=420)
        self.package_slug_field = ft.TextField(label="Paquete del catálogo", hint_text="Escribe el slug exacto", width=420)
        self.revoke_code_field = ft.TextField(label="Licencia que se revocará", width=420)
        self.revoke_reason_field = ft.TextField(label="Motivo", hint_text="Describe brevemente el motivo", width=420, max_length=240)
        self.revoke_confirmation_field = ft.TextField(label="Confirmación", hint_text="Escribe REVOCAR", width=420)
        self.status = ft.Text("Conecta tu cuenta para administrar DaneDesk.", color=ft.Colors.ON_SURFACE_VARIANT)
        self.content = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=16)

    def _card(self, title: str, body: ft.Control, icon: str) -> ft.Control:
        return ft.Card(
            content=ft.Container(
                padding=20,
                content=ft.Column(
                    controls=[ft.Row([ft.Icon(icon, color=ft.Colors.TEAL_300), ft.Text(title, size=18, weight=ft.FontWeight.W_600)]), body],
                    spacing=12,
                ),
            )
        )

    def _notify(self, message: str, error: bool = False) -> None:
        self.page.open(ft.SnackBar(ft.Text(message), bgcolor=ft.Colors.RED_800 if error else ft.Colors.TEAL_800))

    async def _save_token(self) -> None:
        if not self.api.console_token:
            return
        try:
            await self.storage.set(TOKEN_KEY, self.api.console_token)
        except Exception:
            self._notify("El almacén seguro no está disponible; la sesión se cerrará al salir.", error=True)

    async def _clear_token(self) -> None:
        try:
            await self.storage.remove(TOKEN_KEY)
        except Exception:
            pass

    async def restore(self) -> None:
        try:
            token = await self.storage.get(TOKEN_KEY)
        except Exception:
            token = None
        if token:
            self.api.console_token = str(token)
            await self.refresh()
        else:
            self.render_sign_in()

    async def begin_sign_in(self, _: ft.ControlEvent) -> None:
        verifier = secrets.token_urlsafe(64)
        try:
            authorization = self.api.begin_authorization(verifier)
            self.status.value = "Se abrió el navegador. Inicia sesión con GitHub y autoriza esta consola."
            await self.page.launch_url(authorization.verification_uri)
            self.page.update()
            for _ in range(120):
                await asyncio.sleep(2)
                status = self.api.authorization_status(authorization)
                if status == "approved":
                    session = self.api.claim_authorization(authorization, verifier)
                    self.account = session["account"]
                    await self._save_token()
                    await self.refresh()
                    return
                if status in {"expired", "claimed"}:
                    raise ConsoleApiError("La autorización venció o ya fue usada; vuelve a intentarlo")
            raise ConsoleApiError("La autorización venció; vuelve a intentarlo")
        except ConsoleApiError as error:
            self.status.value = "No se pudo conectar la consola."
            self._notify(str(error), error=True)
            self.page.update()

    async def refresh(self, _: ft.ControlEvent | None = None) -> None:
        try:
            self.devices = self.api.devices()
            self.licenses = self.api.licenses()
            self.packages = self.api.catalog()
            self.status.value = f"Sesión protegida de {self.account or 'Foundstore'}"
            self.render_dashboard()
        except ConsoleApiError as error:
            self.api.console_token = ""
            await self._clear_token()
            self.status.value = "La sesión de consola no está disponible."
            self._notify(str(error), error=True)
            self.render_sign_in()

    async def sign_out(self, _: ft.ControlEvent) -> None:
        try:
            self.api.logout()
        except ConsoleApiError:
            pass
        self.api.console_token = ""
        self.account = ""
        await self._clear_token()
        self.render_sign_in()

    def render_sign_in(self) -> None:
        self.content.controls = [
            ft.Container(height=36),
            ft.Icon(ft.Icons.ADMIN_PANEL_SETTINGS_OUTLINED, size=54, color=ft.Colors.TEAL_300),
            ft.Text("Foundstore Console", size=32, weight=ft.FontWeight.BOLD),
            ft.Text("Gestiona tus licencias y DaneDesk desde una sesión protegida. La autorización ocurre en GitHub; esta app no guarda tu token de GitHub.", width=580),
            ft.FilledButton("Conectar con GitHub", icon=ft.Icons.LOGIN, on_click=self.begin_sign_in, height=48),
            self.status,
        ]
        self.page.update()

    async def create_license(self, _: ft.ControlEvent) -> None:
        try:
            created = self.api.create_license()
            self._notify("Licencia creada. Guárdala en un lugar seguro antes de vincular el DaneDesk.")
            await self.refresh()
            self.page.open(ft.SnackBar(ft.Text(f"Nueva licencia: {created.get('license', '')}"), duration=8000))
        except ConsoleApiError as error:
            self._notify(str(error), error=True)

    def _license_row(self, license_item: dict[str, Any]) -> ft.Control:
        code = str(license_item.get("license") or "Código no recuperable")
        status = str(license_item.get("status") or "desconocido")
        return ft.ListTile(
            leading=ft.Icon(ft.Icons.KEY_OUTLINED),
            title=ft.Text(code),
            subtitle=ft.Text(f"{status} · {license_item.get('deviceName') or 'Sin DaneDesk'}"),
        )

    async def request_install(self, _: ft.ControlEvent) -> None:
        device_id = self.device_id_field.value.strip()
        slug = self.package_slug_field.value.strip()
        owned_devices = {str(item.get("id") or "") for item in self.devices}
        available_slugs = {str(item.get("slug") or "") for item in self.packages}
        if not device_id or not slug:
            self._notify("Indica un DaneDesk y un paquete del catálogo antes de solicitar la instalación.", error=True)
            return
        if device_id not in owned_devices or slug not in available_slugs:
            self._notify("El DaneDesk o el paquete indicado no están disponibles en tu cuenta.", error=True)
            return
        if not self.devices or not self.packages:
            self._notify("No hay DaneDesk activo o paquetes disponibles.", error=True)
            return
        try:
            requested = self.api.request_installation(device_id, slug)
            self._notify("Solicitud enviada. El DaneDesk pedirá aprobación local antes de instalar.")
            self.status.value = f"Solicitud {requested.get('requestId', '')} pendiente de aprobación local."
            self.page.update()
        except ConsoleApiError as error:
            self._notify(str(error), error=True)

    async def revoke_license(self, _: ft.ControlEvent) -> None:
        license_code = self.revoke_code_field.value.strip()
        reason = self.revoke_reason_field.value.strip()
        if self.revoke_confirmation_field.value.strip().upper() != "REVOCAR":
            self._notify("Escribe REVOCAR para confirmar la acción irreversible.", error=True)
            return
        if not license_code or not reason:
            self._notify("Indica la licencia y un motivo antes de revocar.", error=True)
            return
        try:
            self.api.revoke_license(license_code, reason)
            self.revoke_code_field.value = ""
            self.revoke_reason_field.value = ""
            self.revoke_confirmation_field.value = ""
            self._notify("La licencia se revocó y el DaneDesk vinculado fue desautorizado.")
            await self.refresh()
        except ConsoleApiError as error:
            self._notify(str(error), error=True)

    def render_dashboard(self) -> None:
        device_rows = [
            ft.ListTile(
                leading=ft.Icon(ft.Icons.COMPUTER_OUTLINED),
                title=ft.Text(str(item.get("displayName") or "DaneDesk")),
                subtitle=ft.Text(f"{item.get('platform') or 'Danenone'} · {item.get('status') or 'desconocido'} · ID {item.get('id') or 'sin datos'} · visto {item.get('lastSeenAt') or 'sin datos'}"),
            )
            for item in self.devices
        ] or [ft.Text("Aún no hay DaneDesk vinculados.")]
        self.content.controls = [
            ft.Row([ft.Text("Foundstore Console", size=26, weight=ft.FontWeight.BOLD), ft.IconButton(ft.Icons.REFRESH, tooltip="Actualizar", on_click=self.refresh), ft.IconButton(ft.Icons.LOGOUT, tooltip="Cerrar sesión", on_click=self.sign_out)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            self.status,
            ft.ResponsiveRow(
                controls=[
                    ft.Container(col={"sm": 12, "md": 6}, content=self._card("DaneDesk", ft.Text(f"{len(self.devices)} dispositivo(s) vinculado(s)"), ft.Icons.COMPUTER_OUTLINED)),
                    ft.Container(col={"sm": 12, "md": 6}, content=self._card("Licencias", ft.Text(f"{len(self.licenses)} licencia(s) en tu cuenta"), ft.Icons.KEY_OUTLINED)),
                ]
            ),
            self._card("DaneDesk", ft.Column(device_rows), ft.Icons.COMPUTER_OUTLINED),
            self._card("Licencias", ft.Column([ft.FilledButton("Crear licencia", icon=ft.Icons.ADD, on_click=self.create_license)] + [self._license_row(item) for item in self.licenses] + [ft.Divider(), ft.Text("Revocación irreversible"), self.revoke_code_field, self.revoke_reason_field, self.revoke_confirmation_field, ft.OutlinedButton("Revocar licencia", icon=ft.Icons.DELETE_OUTLINE, on_click=self.revoke_license)]), ft.Icons.KEY_OUTLINED),
            self._card("Instalaciones", ft.Column([ft.Text("Las solicitudes sólo cambian a instalación en curso tras un evento firmado del agente."), self.device_id_field, self.package_slug_field, ft.OutlinedButton("Solicitar instalación", icon=ft.Icons.DOWNLOAD_OUTLINED, on_click=self.request_install)]), ft.Icons.DOWNLOAD_OUTLINED),
            self._card("Privacidad E2E", ft.Text("Los informes sensibles se mantienen cifrados. La consola Flet no exporta la clave no exportable de la consola web."), ft.Icons.LOCK_OUTLINED),
        ]
        self.page.update()


async def main(page: ft.Page) -> None:
    page.title = "Foundstore Console"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 24
    page.bgcolor = ft.Colors.SURFACE
    console = FoundstoreConsole(page)
    page.add(ft.SafeArea(ft.Container(content=console.content, expand=True), expand=True))
    console.render_sign_in()
    page.run_task(console.restore)


if __name__ == "__main__":
    ft.run(main)
