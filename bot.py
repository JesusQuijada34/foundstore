import os
import telebot
from telebot import types
import json
import requests
from config import Config
import services

# Inicialización del Bot
bot = telebot.TeleBot(Config.TELEGRAM_BOT_TOKEN)

# Diccionario para estados de conversación cifrada (simulado)
# En producción usar Redis o MongoDB para persistencia de sesiones de chat
active_chats = {}

@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    item1 = types.KeyboardButton("🔍 Buscar Desarrollador")
    item2 = types.KeyboardButton("📦 Paquetes iflapp")
    item3 = types.KeyboardButton("📈 Tendencias (Top)")
    markup.add(item1, item2, item3)
    
    bot.reply_to(message, "¡Bienvenido a foundstore Bot! 🚀\n\nAquí puedes encontrar desarrolladores, descargar paquetes y recibir alertas en tiempo real.", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🔍 Buscar Desarrollador")
def search_dev_prompt(message):
    msg = bot.send_message(message.chat.id, "Introduce el username de GitHub del desarrollador que buscas:")
    bot.register_next_step_handler(msg, process_dev_search)

def process_dev_search(message):
    username = message.text.strip()
    accounts = services.load_ondev_accounts()
    
    if username in accounts:
        user = accounts[username]
        telegram_user = user.get("telegram_username")
        
        response = f"👤 *Perfil Encontrado*\n\n"
        response += f"Nombre: {user.get('telegram_name', username)}\n"
        response += f"GitHub: github.com/{username}\n"
        
        markup = types.InlineKeyboardMarkup()
        if telegram_user:
            btn = types.InlineKeyboardButton("💬 Iniciar Chat Cifrado", callback_data=f"chat_{username}")
            markup.add(btn)
        
        bot.send_message(message.chat.id, response, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "No encontré a ese desarrollador en foundstore. Asegúrate de que haya completado el onboarding.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("chat_"))
def initiate_encrypted_chat(call):
    target_username = call.data.split("_")[1]
    bot.answer_callback_query(call.id, "Estableciendo túnel cifrado...")
    
    # Lógica de cifrado de mirrors y túnel (Simulación)
    bot.send_message(call.message.chat.id, f"🔒 *Túnel Seguro Establecido*\n\nAhora puedes escribirle a @{target_username}. Los mensajes se transmiten a través de mirrors cifrados de foundstore.", parse_mode="Markdown")

@bot.message_handler(func=lambda message: message.text == "📦 Paquetes iflapp")
def list_packages(message):
    catalog = services.get_catalog()
    packages = catalog.get("packages", [])
    
    if not packages:
        bot.send_message(message.chat.id, "No hay paquetes disponibles en este momento.")
        return

    markup = types.InlineKeyboardMarkup()
    for pkg in packages[:5]: # Mostrar los primeros 5
        btn = types.InlineKeyboardButton(f"⬇️ {pkg['display_name']}", callback_data=f"pkg_{pkg['name']}")
        markup.add(btn)
    
    bot.send_message(message.chat.id, "📦 *Paquetes iflapp*\nSelecciona un paquete para ver opciones de descarga:", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("pkg_"))
def package_options(call):
    pkg_name = call.data.split("_")[1]
    
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("🤖 Android", callback_data=f"dl_{pkg_name}_android"),
        types.InlineKeyboardButton("🍎 iOS", callback_data=f"dl_{pkg_name}_ios")
    )
    markup.add(
        types.InlineKeyboardButton("🌐 Web", callback_data=f"dl_{pkg_name}_web"),
        types.InlineKeyboardButton("💻 Desktop", callback_data=f"dl_{pkg_name}_desktop")
    )
    
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                         text=f"Escoge la plataforma para *{pkg_name}*:", parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("dl_"))
def generate_encrypted_download(call):
    _, pkg_name, platform = call.data.split("_")
    
    # Simulación de cifrado de mirrors
    mirror_url = f"https://mirror-encrypted.foundstore.im/dl/{pkg_name}/{platform}?token=cifrado_sha256"
    
    bot.send_message(call.message.chat.id, f"✅ *Enlace de Descarga Generado*\n\nPlataforma: {platform.capitalize()}\nEnlace: {mirror_url}\n\n_Este enlace expira en 10 minutos._", parse_mode="Markdown")

if __name__ == "__main__":
    print("Bot iniciado...")
    bot.infinity_polling()
