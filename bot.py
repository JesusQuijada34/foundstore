"""
bot.py - Bot de Telegram de foundstore con:
  - Muro de autenticacion (intercepts todo mensaje de users no vinculados)
  - Comando /code para validar OTP y vincular
  - Handlers de busqueda de devs y paquetes
  - Sincronizacion con la web via MongoDB (storage.py)
  - Cache L1 para evitar pegar a Mongo en cada mensaje
"""
import os
import sys
import asyncio
import logging
from typing import Optional

from config import Config
import storage

# python-telegram-bot v20+ (asyncio)
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes,
)
from telegram.constants import ParseMode

# Logging
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("foundstore-bot")

# Estado de la conversacion cifrada (simulado)
active_chats: dict = {}

# URL base de la web (para callbacks al SSE y para mostrar en mensajes)
WEB_BASE_URL = os.environ.get("WEB_BASE_URL", "https://foundstore.onrender.com").rstrip("/")

# =====================================================================
# MURO DE AUTENTICACION
# =====================================================================
# Cualquier mensaje que NO sea /start o el ingreso de un codigo de 6 digitos
# se intercepta y se muestra el muro pidiendo el codigo OTP.

WALL_MESSAGE = """🔒 *Acceso restringido*

Para usar el bot de foundstore primero tienes que vincular tu cuenta.

📋 *Como vincular:*
1. Ve a *{web}*
2. Inicia sesion con GitHub
3. Abre *Configuracion* (icono de tu avatar)
4. Pulsa *Vincular Telegram* y copia el codigo
5. Escribelo aqui (solo los 6 digitos)

⏱ El codigo expira en 5 minutos.
""".strip()


async def auth_wall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Intercepta cualquier mensaje de un user no vinculado."""
    user = update.effective_user
    if not user or not update.effective_message:
        return

    # Si ya paso el muro, dejar pasar
    if context.user_data.get("authenticated"):
        return  # no retorna estado, el siguiente handler se encarga

    text = (update.effective_message.text or "").strip()
    chat_id = update.effective_message.chat_id

    # Caso especial: el user escribe un codigo de 6 digitos
    if text and text.isdigit() and len(text) == 6:
        return await handle_otp_code(update, context)

    # /start siempre se permite (es el punto de entrada)
    if text.startswith("/start"):
        return  # el handler de /start lo procesa

    # Cualquier otra cosa -> muro
    await update.effective_message.reply_text(
        WALL_MESSAGE.format(web=WEB_BASE_URL),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 Ir a foundstore", url=WEB_BASE_URL),
        ]]),
    )


# =====================================================================
# HANDLERS
# =====================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /start: bienvenida + muro si no esta vinculado."""
    user = update.effective_user
    if not user:
        return

    # Comprobar vinculacion (cache L1)
    linked = storage.get_user_by_telegram_id(user.id)
    if linked:
        context.user_data["authenticated"] = True
        context.user_data["github_username"] = linked["github_username"]
        markup = ReplyKeyboardMarkup(
            [
                [KeyboardButton("🔍 Buscar Desarrollador")],
                [KeyboardButton("📦 Paquetes iflapp")],
                [KeyboardButton("📈 Tendencias (Top)")],
            ],
            resize_keyboard=True,
        )
        await update.message.reply_text(
            f"¡Bienvenido de vuelta @{linked['github_username']}! 🚀\n\n"
            "Aqui puedes encontrar desarrolladores, descargar paquetes y "
            "recibir alertas en tiempo real.",
            reply_markup=markup,
        )
        return

    # No vinculado -> muro
    await update.message.reply_text(
        WALL_MESSAGE.format(web=WEB_BASE_URL),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 Ir a foundstore", url=WEB_BASE_URL),
        ]]),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /help."""
    if not context.user_data.get("authenticated"):
        await auth_wall(update, context)
        return
    await update.message.reply_text(
        "🤖 *Comandos disponibles*\n\n"
        "/start - Reiniciar\n"
        "/code - Vincular cuenta con codigo OTP\n"
        "/unlink - Desvincular esta cuenta de Telegram\n"
        "/help - Esta ayuda\n\n"
        "Tambien puedes usar los botones del teclado.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def unlink_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /unlink: desvincula la cuenta de Telegram."""
    user = update.effective_user
    gh = context.user_data.get("github_username")
    if not user or not gh:
        await update.message.reply_text("No tienes cuenta vinculada.")
        return

    ok = storage.unlink_telegram(gh)
    if ok:
        context.user_data.clear()
        await update.message.reply_text(
            "✅ Cuenta desvinculada correctamente. "
            "Vuelve a la web para vincular de nuevo cuando quieras.",
        )
    else:
        await update.message.reply_text("❌ Error al desvincular. Intentalo mas tarde.")


async def handle_otp_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procesa un codigo OTP de 6 digitos escrito por el user."""
    user = update.effective_user
    if not user or not update.effective_message:
        return
    code = (update.effective_message.text or "").strip()

    # Si ya esta autenticado y escribe numeros, ignorar (puede estar pegando otra cosa)
    if context.user_data.get("authenticated") and not context.user_data.get("awaiting_otp"):
        return

    # Validar contra MongoDB
    result = storage.consume_otp_by_hash(code)

    if not result.get("ok"):
        # Incrementar intentos (rate-limit)
        storage.increment_otp_attempts(code)
        err = result.get("error", "unknown")
        if err == "too_many_attempts":
            await update.message.reply_text(
                "❌ *Demasiados intentos.*\n\n"
                "Genera un codigo nuevo desde la web.",
                parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await update.message.reply_text(
                "❌ *Codigo invalido o expirado.*\n\n"
                "Vuelve a la web y genera uno nuevo.",
                parse_mode=ParseMode.MARKDOWN,
            )
        return

    github_username = result["github_username"]

    # Vincular en MongoDB
    ok = storage.link_telegram(
        github_username=github_username,
        telegram_id=user.id,
        telegram_username=user.username,
        telegram_name=user.full_name,
    )
    if not ok:
        await update.message.reply_text("❌ Error guardando la vinculacion. Intentalo de nuevo.")
        return

    # Marcar sesion en el bot
    context.user_data["authenticated"] = True
    context.user_data["github_username"] = github_username
    context.user_data["awaiting_otp"] = False

    # Notificar a la web via SSE (la web del username recibe el evento)
    try:
        from notifications import notify_user
        notify_user(
            github_username,
            title="Telegram vinculado",
            desc=f"@{user.username or user.first_name} acaba de vincular su cuenta.",
            icon="telegram",
        )
    except Exception:
        pass

    markup = ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔍 Buscar Desarrollador")],
            [KeyboardButton("📦 Paquetes iflapp")],
            [KeyboardButton("📈 Tendencias (Top)")],
        ],
        resize_keyboard=True,
    )
    await update.message.reply_text(
        f"✅ *Cuenta vinculada correctamente*\n\n"
        f"GitHub: *@{github_username}*\n"
        f"Telegram: *@{user.username or user.id}*\n\n"
        f"Ya puedes usar el bot. Escribe /help para ver comandos.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=markup,
    )


# =====================================================================
# Handlers autenticados (busqueda, paquetes, etc)
# =====================================================================

async def must_be_authed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not context.user_data.get("authenticated"):
        await auth_wall(update, context)
        return False
    return True


async def search_dev_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await must_be_authed(update, context):
        return
    msg = await update.message.reply_text("Introduce el username de GitHub del desarrollador que buscas:")
    context.user_data["awaiting_dev_search"] = True


async def process_dev_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get("awaiting_dev_search"):
        return
    context.user_data["awaiting_dev_search"] = False
    username = (update.message.text or "").strip().lstrip("@")
    if not username:
        return

    user = storage.get_user(username)
    if not user or not user.get("is_active"):
        await update.message.reply_text("No encontre a ese desarrollador en foundstore.")
        return

    tg = user.get("telegram_username")
    response = f"👤 *Perfil Encontrado*\n\n"
    response += f"Nombre: {user.get('telegram_name') or username}\n"
    response += f"GitHub: github.com/{username}\n"

    markup = InlineKeyboardMarkup()
    if tg:
        markup.add(InlineKeyboardButton("💬 Iniciar Chat Cifrado", callback_data=f"chat_{username}"))
    await update.message.reply_text(
        response, parse_mode=ParseMode.MARKDOWN, reply_markup=markup
    )


async def initiate_chat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("Estableciendo tunel cifrado...")
    target = query.data.split("_", 1)[1]
    await query.message.reply_text(
        f"🔒 *Tunel Seguro Establecido*\n\n"
        f"Ahora puedes escribirle a @{target}. "
        f"Los mensajes se transmiten a traves de mirrors cifrados de foundstore.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def list_packages_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await must_be_authed(update, context):
        return
    # Carga el catalogo global desde la web (cached en services.py)
    try:
        import requests
        r = requests.get(f"{WEB_BASE_URL}/api/global_catalog", timeout=5)
        apps = (r.json() or {}).get("apps", []) if r.ok else []
    except Exception:
        apps = []
    if not apps:
        await update.message.reply_text("No hay paquetes disponibles en este momento.")
        return
    markup = InlineKeyboardMarkup()
    for pkg in apps[:5]:
        markup.add(InlineKeyboardButton(
            f"⬇️ {pkg.get('name', '?')}",
            callback_data=f"pkg_{pkg.get('packagename', '')}"
        ))
    await update.message.reply_text(
        "📦 *Paquetes iflapp*\nSelecciona uno para ver opciones:",
        parse_mode=ParseMode.MARKDOWN, reply_markup=markup,
    )


async def package_options_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    pkg_name = query.data.split("_", 1)[1]
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🤖 Android", callback_data=f"dl_{pkg_name}_android"),
            InlineKeyboardButton("🍎 iOS", callback_data=f"dl_{pkg_name}_ios"),
        ],
        [
            InlineKeyboardButton("🌐 Web", callback_data=f"dl_{pkg_name}_web"),
            InlineKeyboardButton("💻 Desktop", callback_data=f"dl_{pkg_name}_desktop"),
        ],
    ])
    try:
        await query.edit_message_text(
            f"Escoge la plataforma para *{pkg_name}*:",
            parse_mode=ParseMode.MARKDOWN, reply_markup=markup,
        )
    except Exception:
        pass


async def generate_download_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, pkg_name, platform = query.data.split("_", 3)
    mirror_url = f"https://mirror-encrypted.foundstore.im/dl/{pkg_name}/{platform}?token=cifrado_sha256"
    await query.message.reply_text(
        f"✅ *Enlace de Descarga Generado*\n\n"
        f"Plataforma: {platform.capitalize()}\n"
        f"Enlace: {mirror_url}\n\n"
        f"_Este enlace expira en 10 minutos._",
        parse_mode=ParseMode.MARKDOWN,
    )


# =====================================================================
# MAIN
# =====================================================================
def main() -> None:
    if not Config.TELEGRAM_BOT_TOKEN:
        print("[bot] ERROR: TELEGRAM_BOT_TOKEN no configurado")
        sys.exit(1)

    print(f"[bot] foundstore bot v2 arrancando...")
    print(f"[bot] MongoDB ok: {storage.mongo.ok}")
    print(f"[bot] Web: {WEB_BASE_URL}")

    app = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("code", handle_otp_code))
    app.add_handler(CommandHandler("unlink", unlink_cmd))

    # Busqueda
    app.add_handler(MessageHandler(
        filters.Regex("^🔍 Buscar Desarrollador$"), search_dev_prompt
    ))
    app.add_handler(MessageHandler(
        filters.Regex("^📦 Paquetes iflapp$"), list_packages_cmd
    ))

    # Callback queries (paquetes, chats)
    app.add_handler(CallbackQueryHandler(initiate_chat_cb, pattern=r"^chat_"))
    app.add_handler(CallbackQueryHandler(package_options_cb, pattern=r"^pkg_"))
    app.add_handler(CallbackQueryHandler(generate_download_cb, pattern=r"^dl_"))

    # === MURO ===
    # Captura cualquier mensaje que NO sea un comando ni los botones
    # de teclado. Es el ultimo handler, asi que solo se ejecuta si
    # nadie mas lo proceso.
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        auth_wall,
    ), group=99)

    # Rehidratacion: si el user se autentico, sus siguientes mensajes
    # caen en handlers especificos. Si no, auth_wall los intercepta.

    print("[bot] Bot iniciado, esperando mensajes...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
