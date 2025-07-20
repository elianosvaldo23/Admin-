import logging
import re
import html
import json
import os
import time
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode, ChatType
from telegram.error import TelegramError, BadRequest

from database import Database
from auto_posts import AutoPostManager

# Configuración de logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuración del bot
TOKEN = os.getenv("BOT_TOKEN", "7675635354:AAGDEThhiIrNuliQ3EWufVMjCK8z2I0ma_0")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1742433244"))
GROUP_ID = os.getenv("GROUP_ID", "botoneraMultimediaTv")
CATEGORY_CHANNEL_ID = int(os.getenv("CATEGORY_CHANNEL_ID", "-1002259108243"))

# Categorías con sus URLs de post
CATEGORIES = {
    "Películas y Series 🖥": "https://t.me/c/2259108243/4",
    "Anime 💮": "https://t.me/c/2259108243/18",
    "Música 🎶": "https://t.me/c/2259108243/20",
    "Videojuegos 🎮": "https://t.me/c/2259108243/22",
    "Memes y Humor 😂": "https://t.me/c/2259108243/24",
    "Frases 📝": "https://t.me/c/2259108243/26",
    "Libros 📚": "https://t.me/c/2259108243/28",
    "Wallpapers 🌆": "https://t.me/c/2259108243/30",
    "Fotografía 📸": "https://t.me/c/2259108243/42",
    "Chicas y Belleza 👩‍🦰💄": "https://t.me/c/2259108243/44",
    "Apks 📱": "https://t.me/c/2259108243/46",
    "Bins y Cuentas 💳": "https://t.me/c/2259108243/48",
    "Redes Sociales 😎": "https://t.me/c/2259108243/51",
    "Noticias 🧾": "https://t.me/c/2259108243/53",
    "Deportes 🥇": "https://t.me/c/2259108243/56",
    "Grupos 👥": "https://t.me/c/2259108243/60",
    "Otros ♾": "https://t.me/c/2259108243/62",
    "+18 🔥": "https://t.me/c/2259108243/64",
}

# Mensaje de bienvenida predeterminado
DEFAULT_WELCOME_MESSAGE = "Hola bienvenido al grupo Botonera Multimedia-TV"

# Configuración anti-spam
SPAM_WINDOW = 60  # segundos
SPAM_LIMIT = 5  # mensajes
SPAM_MUTE_TIME = 300  # segundos (5 minutos)

# Almacenamiento en memoria
pending_submissions = {}
admin_rejecting = {}
custom_welcome = {
    "message": DEFAULT_WELCOME_MESSAGE,
    "buttons": [
        {"text": "Canal Principal", "url": "https://t.me/botoneraMultimediaTv"},
        {"text": "Categorías", "url": "https://t.me/c/2259108243/2"}
    ]
}
user_message_count = defaultdict(list)
muted_users = {}
user_last_activity = {}

# Instancia global de la base de datos y administrador de posts
db = Database()
auto_post_manager = None

async def get_channel_member_count(context: ContextTypes.DEFAULT_TYPE, channel_username: str) -> int:
    """Obtiene el número de miembros de un canal."""
    try:
        chat = await context.bot.get_chat(f"@{channel_username}")
        return chat.member_count if chat.member_count else 0
    except:
        return 0

async def is_admin(user_id, chat_id, context):
    """Verifica si un usuario es administrador del chat."""
    if user_id == ADMIN_ID:
        return True
    
    try:
        chat_member = await context.bot.get_chat_member(chat_id, user_id)
        return chat_member.status in ["creator", "administrator"]
    except TelegramError:
        return False

def check_spam(user_id):
    """Verifica si un usuario está enviando spam."""
    current_time = time.time()
    
    # Eliminar mensajes antiguos
    user_message_count[user_id] = [t for t in user_message_count[user_id] if current_time - t < SPAM_WINDOW]
    
    # Añadir mensaje actual
    user_message_count[user_id].append(current_time)
    
    # Verificar límite
    return len(user_message_count[user_id]) > SPAM_LIMIT

def format_time_delta(seconds):
    """Formatea un número de segundos en un formato legible."""
    if seconds < 60:
        return f"{seconds} segundos"
    elif seconds < 3600:
        return f"{seconds // 60} minutos"
    elif seconds < 86400:
        return f"{seconds // 3600} horas"
    else:
        return f"{seconds // 86400} días"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja el comando /start."""
    if update.effective_chat.type == ChatType.PRIVATE:
        user = update.effective_user
        
        # Crear teclado con botones
        keyboard = [
            [InlineKeyboardButton("📚 Comandos", callback_data="show_commands")],
            [InlineKeyboardButton("📊 Estadísticas", callback_data="show_stats")],
            [InlineKeyboardButton("🔍 Ver Categorías", callback_data="show_categories")],
            [InlineKeyboardButton("➕ Añadir Canal", callback_data="add_channel_help")],
            [InlineKeyboardButton("📣 Canales y Grupos 👥", callback_data="my_channels")]
        ]
        
        if user.id == ADMIN_ID:
            keyboard.append([InlineKeyboardButton("⚙️ Panel de Administrador", callback_data="admin_panel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_html(
            f"Hola {user.mention_html()}! Soy el bot administrador de Botonera Multimedia-TV.\n\n"
            f"Puedo ayudarte a gestionar el grupo y procesar solicitudes de canales.\n\n"
            f"Selecciona una opción para continuar:",
            reply_markup=reply_markup
        )
    else:
        # En grupos, mostrar mensaje de bienvenida con el botón de canales
        keyboard = []
        row = []
        for i, button in enumerate(custom_welcome["buttons"]):
            row.append(InlineKeyboardButton(button["text"], url=button["url"]))
            if (i + 1) % 2 == 0 or i == len(custom_welcome["buttons"]) - 1:
                keyboard.append(row)
                row = []
        
        # Añadir botón de canales y grupos
        keyboard.append([InlineKeyboardButton("📣 Canales y Grupos 👥", callback_data="my_channels")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "¡Hola! Soy el bot administrador de este grupo. Usa los botones para navegar.",
            reply_markup=reply_markup
        )
    
    # Actualizar estadísticas
    if update.effective_user:
        await db.update_user_stats(update.effective_user.id, update.effective_chat.id, "commands")

async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Da la bienvenida a nuevos miembros del grupo."""
    if not update.message or not update.message.new_chat_members:
        return
    
    for new_user in update.message.new_chat_members:
        # Omitir si el nuevo miembro es el bot
        if new_user.id == context.bot.id:
            continue
        
        # Crear mensaje de bienvenida con botones
        keyboard = []
        row = []
        for i, button in enumerate(custom_welcome["buttons"]):
            row.append(InlineKeyboardButton(button["text"], url=button["url"]))
            if (i + 1) % 2 == 0 or i == len(custom_welcome["buttons"]) - 1:
                keyboard.append(row)
                row = []
        
        # Añadir botones adicionales
        keyboard.append([
            InlineKeyboardButton("📚 Reglas del Grupo", callback_data="show_rules"),
            InlineKeyboardButton("🔍 Ver Categorías", callback_data="show_categories")
        ])
        
        # Añadir botón de canales y grupos
        keyboard.append([InlineKeyboardButton("📣 Canales y Grupos 👥", callback_data="my_channels")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Enviar mensaje de bienvenida
        await update.message.reply_html(
            f"{custom_welcome['message']}, {new_user.mention_html()}!\n\n"
            f"Por favor, lee las reglas del grupo y disfruta de tu estancia.",
            reply_markup=reply_markup
        )

async def miscanales_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando MisCanales para usuarios."""
    await show_my_channels(update, context, is_callback=False)

async def show_my_channels(update, context, is_callback=True):
    """Muestra los canales del usuario."""
    user_id = update.effective_user.id
    
    # Obtener canales del usuario
    user_channels = await db.get_user_channels(user_id)
    
    if not user_channels:
        text = ("📣 Canales y Grupos 👥\n\n"
               "☁️ Gestiona los canales o grupos que has añadido a las Categorías\n\n"
               "📣 Canales: 0\n"
               "👥 Grupos: 0\n\n"
               "No has añadido ningún canal aún.")
        
        keyboard = [[InlineKeyboardButton("➕ Añadir Canal", callback_data="add_channel_help")]]
        if is_callback:
            keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if is_callback:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, reply_markup=reply_markup)
        return
    
    # Separar canales y grupos
    channels = [ch for ch in user_channels if not ch['channel_username'].startswith('g_')]
    groups = [ch for ch in user_channels if ch['channel_username'].startswith('g_')]
    
    # Obtener número de suscriptores
    total_channel_subs = 0
    total_group_subs = 0
    
    text = ("📣 Canales y Grupos 👥\n\n"
           "☁️ Gestiona los canales o grupos que has añadido a las Categorías\n\n")
    
    # Calcular suscriptores totales
    for channel in channels:
        member_count = await get_channel_member_count(context, channel['channel_username'])
        total_channel_subs += member_count
    
    for group in groups:
        member_count = await get_channel_member_count(context, group['channel_username'].replace('g_', ''))
        total_group_subs += member_count
    
    text += f"📣 Canales: {len(channels)}\n"
    text += f"    ┗👤{total_channel_subs}\n"
    text += f"👥 Grupos: {len(groups)}\n"
    text += f"    ┗👤{total_group_subs}\n\n"
    
    # Listar todos los canales
    all_channels = channels + groups
    keyboard = []
    
    for i, channel in enumerate(all_channels, 1):
        is_group = channel['channel_username'].startswith('g_')
        username = channel['channel_username'].replace('g_', '') if is_group else channel['channel_username']
        member_count = await get_channel_member_count(context, username)
        
        icon = "👥" if is_group else "📣"
        text += f"{i}. {icon}  {channel['channel_name']}\n"
        text += f"      ┗👤{member_count}\n"
        
        # Crear botones para cada canal
        row = [
            InlineKeyboardButton(f"#{i}", url=f"https://t.me/{username}"),
            InlineKeyboardButton("📝", callback_data=f"edit_channel_{channel['_id']}"),
            InlineKeyboardButton("🗑️", callback_data=f"delete_channel_{channel['_id']}")
        ]
        keyboard.append(row)
    
    if is_callback:
        keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data="back_to_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if is_callback:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def process_channel_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Procesa solicitudes de canales."""
    if not update.message or not update.message.text:
        return
    
    message_text = update.message.text
    user = update.effective_user
    
    if "#" not in message_text:
        return
    
    try:
        # Extraer categoría usando regex
        category_match = re.search(r'#([^\n]+)', message_text)
        if not category_match:
            return
        
        category_text = category_match.group(1).strip()
        
        # Verificar si es una categoría válida
        valid_category = None
        for cat in CATEGORIES.keys():
            if category_text.lower() in cat.lower():
                valid_category = cat
                break
        
        if not valid_category:
            await update.message.reply_text(
                f"❌ Categoría no reconocida: {category_text}\n"
                f"Por favor, usa una de las categorías disponibles."
            )
            return
        
        # Extraer información del canal
        lines = message_text.split('\n')
        channel_name = None
        channel_username = None
        channel_id = None
        channel_link = None
        
        for i, line in enumerate(lines):
            if '#' in line and i < len(lines) - 1:
                channel_name = lines[i + 1].strip()
            
            if '@' in line and 'admin' not in line.lower():
                username_match = re.search(r'@(\w+)', line)
                if username_match:
                    channel_username = username_match.group(1)
            
            if 'ID' in line or 'id' in line:
                id_match = re.search(r'[-]?\d+', line)
                if id_match:
                    channel_id = id_match.group(0)
            
            # Buscar enlaces de invitación
            if 'https://t.me/' in line and '+' in line:
                link_match = re.search(r'https://t\.me/\+[A-Za-z0-9_-]+', line)
                if link_match:
                    channel_link = link_match.group(0)
        
        if not (channel_name and channel_username and channel_id):
            await update.message.reply_html(
                "❌ <b>Formato incorrecto</b>. Por favor, usa el siguiente formato:\n\n"
                "#Categoría\n"
                "Nombre del Canal\n"
                "@username_canal\n"
                "ID -100xxxxxxxxxx\n"
                "@admin bot añadido"
            )
            return
        
        # Verificar si el canal ya existe
        existing_channel = await db.get_channel_by_username(channel_username)
        if existing_channel:
            await update.message.reply_text(
                f"❌ El canal @{channel_username} ya está registrado en la categoría {existing_channel['category']}."
            )
            return
        
        # Almacenar solicitud
        submission_id = f"{user.id}_{update.message.message_id}"
        submission_data = {
            "user_id": user.id,
            "user_name": user.full_name,
            "category": valid_category,
            "channel_name": channel_name,
            "channel_username": channel_username,
            "channel_id": channel_id,
            "channel_link": channel_link or f"https://t.me/{channel_username}",
            "message_id": update.message.message_id,
            "chat_id": update.effective_chat.id
        }
        
        pending_submissions[submission_id] = submission_data
        await db.save_pending_submission(submission_id, submission_data)
        
        # Notificar al administrador
        keyboard = [
            [
                InlineKeyboardButton("✅ Aprobar", callback_data=f"approve_{submission_id}"),
                InlineKeyboardButton("❌ Rechazar", callback_data=f"reject_{submission_id}")
            ],
            [
                InlineKeyboardButton("🔍 Ver Canal", url=f"https://t.me/{channel_username}"),
                InlineKeyboardButton("📋 Ver Categoría", url=CATEGORIES[valid_category])
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        admin_message = (
            f"📢 <b>Nueva solicitud de canal</b>\n\n"
            f"<b>Usuario:</b> {user.mention_html()}\n"
            f"<b>Categoría:</b> {valid_category}\n"
            f"<b>Canal:</b> {html.escape(channel_name)}\n"
            f"<b>Username:</b> @{html.escape(channel_username)}\n"
            f"<b>ID:</b> {html.escape(channel_id)}\n\n"
            f"¿Deseas aprobar esta solicitud?"
        )
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        
        # Notificar al usuario
        user_keyboard = [
            [
                InlineKeyboardButton("📊 Estado de Solicitud", callback_data=f"check_status_{submission_id}"),
                InlineKeyboardButton("❌ Cancelar Solicitud", callback_data=f"cancel_{submission_id}")
            ]
        ]
        user_reply_markup = InlineKeyboardMarkup(user_keyboard)
        
        await update.message.reply_html(
            f"✅ Tu solicitud para añadir el canal <b>{html.escape(channel_name)}</b> a la categoría <b>{valid_category}</b> "
            f"ha sido enviada al administrador para su aprobación.",
            reply_markup=user_reply_markup,
            reply_to_message_id=update.message.message_id
        )
        
        await db.update_user_stats(user.id, update.effective_chat.id, "messages")
        
    except Exception as e:
        logger.error(f"Error processing channel submission: {e}")
        await update.message.reply_text(
            "❌ Ocurrió un error al procesar tu solicitud. Por favor, verifica el formato e intenta nuevamente."
        )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja callbacks de botones."""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    user_id = update.effective_user.id
    
    # Manejar aprobación/rechazo de solicitudes
    if callback_data.startswith("approve_") or callback_data.startswith("reject_"):
        if user_id != ADMIN_ID:
            await query.edit_message_text("Solo el administrador principal puede aprobar o rechazar solicitudes.")
            return
        
        submission_id = callback_data.split("_", 1)[1]
        
        if submission_id not in pending_submissions:
            await query.edit_message_text("Esta solicitud ya no está disponible o ha sido procesada.")
            return
        
        submission = pending_submissions[submission_id]
        
        if callback_data.startswith("approve_"):
            try:
                # Guardar el canal en la base de datos
                success = await db.save_approved_channel(
                    submission["channel_id"],
                    submission["channel_name"],
                    submission["channel_username"],
                    submission["category"],
                    submission["user_id"],
                    submission.get("channel_link", f"https://t.me/{submission['channel_username']}")
                )
                
                if success:
                    # Actualizar mensaje en el canal de categorías
                    await update_category_message(context, submission["category"])
                    
                    # Notificar al administrador
                    channels_in_category = await db.get_approved_channels(submission["category"])
                    await query.edit_message_text(
                        f"✅ Canal aprobado y añadido a la categoría {submission['category']}.\n"
                        f"Total de canales en la categoría: {len(channels_in_category)}"
                    )
                    
                    # Notificar al usuario
                    user_keyboard = [
                        [
                            InlineKeyboardButton("🔍 Ver Categoría", url=CATEGORIES[submission["category"]]),
                            InlineKeyboardButton("📢 Compartir Canal", 
                                url=f"https://t.me/share/url?url=https://t.me/{submission['channel_username']}")
                        ]
                    ]
                    user_reply_markup = InlineKeyboardMarkup(user_keyboard)
                    
                    await context.bot.send_message(
                        chat_id=submission["chat_id"],
                        text=f"✅ Tu canal <b>{html.escape(submission['channel_name'])}</b> ha sido aprobado y añadido a la categoría <b>{submission['category']}</b>.",
                        parse_mode=ParseMode.HTML,
                        reply_to_message_id=submission["message_id"],
                        reply_markup=user_reply_markup
                    )
                else:
                    await query.edit_message_text("❌ Error al guardar el canal en la base de datos.")
                
                # Eliminar solicitud
                await db.delete_pending_submission(submission_id)
                del pending_submissions[submission_id]
                
            except Exception as e:
                logger.error(f"Error in approval process: {e}")
                await query.edit_message_text(f"❌ Error en el proceso de aprobación: {str(e)}")
            
            return
            
        elif callback_data.startswith("reject_"):
            # Mostrar opciones de rechazo
            keyboard = [
                [InlineKeyboardButton("Canal duplicado", callback_data=f"reject_reason_{submission_id}_duplicado")],
                [InlineKeyboardButton("Contenido inapropiado", callback_data=f"reject_reason_{submission_id}_inapropiado")],
                [InlineKeyboardButton("Información incorrecta", callback_data=f"reject_reason_{submission_id}_incorrecto")],
                [InlineKeyboardButton("Categoría equivocada", callback_data=f"reject_reason_{submission_id}_categoria")],
                [InlineKeyboardButton("Otro motivo (escribir)", callback_data=f"reject_custom_{submission_id}")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"Selecciona el motivo del rechazo para el canal {submission['channel_name']}:",
                reply_markup=reply_markup
            )
            return
    
    # Manejar motivos de rechazo
    elif callback_data.startswith("reject_reason_"):
        parts = callback_data.split("_")
        submission_id = parts[2]
        reason_code = parts[3]
        
        if submission_id not in pending_submissions:
            await query.edit_message_text("Esta solicitud ya no está disponible.")
            return
        
        submission = pending_submissions[submission_id]
        
        reason_messages = {
            "duplicado": "El canal ya existe en nuestras categorías.",
            "inapropiado": "El contenido del canal no cumple con nuestras normas.",
            "incorrecto": "La información proporcionada es incorrecta o incompleta.",
            "categoria": "La categoría seleccionada no es adecuada para este canal."
        }
        
        reason = reason_messages.get(reason_code, "No cumple con los requisitos.")
        
        try:
            # Notificar al usuario sobre el rechazo
            user_keyboard = [
                [
                    InlineKeyboardButton("🔄 Enviar Nueva Solicitud", callback_data="add_channel_help"),
                    InlineKeyboardButton("❓ Ayuda", callback_data="help_channels")
                ]
            ]
            user_reply_markup = InlineKeyboardMarkup(user_keyboard)
            
            await context.bot.send_message(
                chat_id=submission["chat_id"],
                text=f"❌ Tu solicitud para añadir el canal <b>{html.escape(submission['channel_name'])}</b> "
                     f"a la categoría <b>{submission['category']}</b> ha sido rechazada.\n\n"
                     f"<b>Motivo:</b> {html.escape(reason)}",
                parse_mode=ParseMode.HTML,
                reply_to_message_id=submission["message_id"],
                reply_markup=user_reply_markup
            )
            
            await query.edit_message_text(
                f"✅ Rechazo enviado al usuario para el canal {submission['channel_name']}.\n"
                f"Motivo: {reason}"
            )
            
            # Eliminar solicitud
            await db.delete_pending_submission(submission_id)
            del pending_submissions[submission_id]
            
        except Exception as e:
            logger.error(f"Error sending rejection: {e}")
            await query.edit_message_text(f"❌ Error al enviar el rechazo: {str(e)}")
        
        return
    
    # Manejar verificación de estado
    elif callback_data.startswith("check_status_"):
        submission_id = callback_data.split("_")[2]
        
        if submission_id not in pending_submissions:
            await query.edit_message_text(
                "Esta solicitud ya no está disponible o ha sido procesada. Si fue aprobada, deberías haber recibido una notificación."
            )
            return
        
        submission = pending_submissions[submission_id]
        
        if user_id != submission["user_id"]:
            await query.answer("Solo el usuario que envió la solicitud puede verificar su estado.", show_alert=True)
            return
        
        await query.edit_message_text(
            f"ℹ️ Tu solicitud para añadir el canal <b>{html.escape(submission['channel_name'])}</b> "
            f"a la categoría <b>{submission['category']}</b> está pendiente de aprobación por el administrador.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Cancelar Solicitud", callback_data=f"cancel_{submission_id}")]
            ])
        )
        return
    
    # Manejar mostrar mis canales
    elif callback_data == "my_channels":
        await show_my_channels(update, context)
        return
    
# Manejar editar canal
    elif callback_data. startswith("edit_channel_"):
        channel_id = callback_data.split("_")[2]
        channel = await db.get_channel_by_id(channel_id)
    
        if not channel or channel['added_by'] != user_id:
            await query.answer("No tienes permisos para editar este canal.", show_alert=True)
            return
    
    # Obtener el nombre de usuario del canal
        channel_username = channel["channel_username"]
    
    # Construir el enlace del canal
        channel_link = channel.get('channel_link', f"https://t.me/{channel_username}")
    
        text = (f"✏️ Editar\n\n"
                f"🏷 {channel['channel_name']}\n"
                f"🆔 {channel['channel_id']}\n"
                f"🔗 {channel_link}")
    
        keyboard = [
         [InlineKeyboardButton("📝Cambiar Nombre", callback_data=f"edit_name_{channel_id}")],
        [InlineKeyboardButton("📝 Modificar Enlace", callback_data=f"edit_link_{channel_id}")],
        [InlineKeyboardButton("Volver 🔙", callback_data="my_channels")]
    ]
    
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    
    # Manejar eliminar canal
    elif callback_data.startswith("delete_channel_"):
        channel_id = callback_data.split("_")[2]
        channel = await db.get_channel_by_id(channel_id)
        
        if not channel or channel['added_by'] != user_id:
            await query.answer("No tienes permisos para eliminar este canal.", show_alert=True)
            return
        
        # Eliminar canal
        success = await db.delete_channel(channel_id)
        if success:
            # Actualizar mensaje de categoría
            await update_category_message(context, channel['category'])
            
            await query.answer("Canal eliminado exitosamente.", show_alert=True)
            await show_my_channels(update, context)
        else:
            await query.answer("Error al eliminar el canal.", show_alert=True)
        return
    
    # Otros callbacks existentes...
    # (Incluir aquí el resto de los callbacks del código original)
    
    # Manejar mostrar categorías
    if callback_data == "show_categories":
        categories_text = "<b>📚 Categorías disponibles:</b>\n\n"
        
        keyboard = []
        for i, (category, url) in enumerate(CATEGORIES.items(), 1):
            categories_text += f"{i}. {category}\n"
            if i % 2 == 1:
                row = [InlineKeyboardButton(category, url=url)]
            else:
                row.append(InlineKeyboardButton(category, url=url))
                keyboard.append(row)
        
        if len(CATEGORIES) % 2 == 1:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            categories_text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        return
    
    # Manejar volver al menú principal
    elif callback_data == "back_to_main":
        keyboard = [
            [InlineKeyboardButton("📚 Comandos", callback_data="show_commands")],
            [InlineKeyboardButton("📊 Estadísticas", callback_data="show_stats")],
            [InlineKeyboardButton("🔍 Ver Categorías", callback_data="show_categories")],
            [InlineKeyboardButton("➕ Añadir Canal", callback_data="add_channel_help")],
            [InlineKeyboardButton("📣 Canales y Grupos 👥", callback_data="my_channels")]
        ]
        
        if user_id == ADMIN_ID:
            keyboard.append([InlineKeyboardButton("⚙️ Panel de Administrador", callback_data="admin_panel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"Hola {update.effective_user.first_name}! Soy el bot administrador de Botonera Multimedia-TV.\n\n"
            f"Puedo ayudarte a gestionar el grupo y procesar solicitudes de canales.\n\n"
            f"Selecciona una opción para continuar:",
            reply_markup=reply_markup
        )
        return

async def update_category_message(context: ContextTypes.DEFAULT_TYPE, category: str):
    """Actualiza el mensaje de una categoría en el canal."""
    try:
        post_url = CATEGORIES[category]
        post_message_id = int(post_url.split("/")[-1])
        
        channels = await db.get_approved_channels(category)
        
        new_text = f"{category}\n\n"
        
        for channel in channels:
            channel_link = channel.get('channel_link', f"https://t.me/{channel['channel_username']}")
            new_text += f"[{channel['channel_name']}]({channel_link})\n\n"
        
        if channels:
            new_text = new_text.rstrip('\n')
        
        await context.bot.edit_message_text(
            chat_id=CATEGORY_CHANNEL_ID,
            message_id=post_message_id,
            text=new_text,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Error updating category message: {e}")

# Comandos administrativos
async def del_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Elimina un canal de las categorías y base de datos."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Solo el administrador puede usar este comando.")
        return
    
    if not context.args:
        await update.message.reply_text("Uso: /del @username_canal")
        return
    
    username = context.args[0].replace('@', '')
    
    channel = await db.get_channel_by_username(username)
    if not channel:
        await update.message.reply_text(f"Canal @{username} no encontrado.")
        return
    
    success = await db.delete_channel(channel['_id'])
    if success:
        await update_category_message(context, channel['category'])
        await update.message.reply_text(f"✅ Canal @{username} eliminado exitosamente.")
    else:
        await update.message.reply_text("❌ Error al eliminar el canal.")

async def edit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Edita un canal de las categorías y base de datos."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Solo el administrador puede usar este comando.")
        return
    
    await update.message.reply_text("Función de edición disponible en el menú de administrador.")

async def a_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Añade un canal a la lista de publicación automática."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Solo el administrador puede usar este comando.")
        return
    
    if not context.args:
        await update.message.reply_text("Uso: /A @username_canal")
        return
    
    username = context.args[0].replace('@', '')
    
    success = await auto_post_manager.add_channel(username)
    if success:
        await update.message.reply_text(f"✅ Canal @{username} añadido a la lista de publicación automática.")
    else:
        await update.message.reply_text("❌ Error al añadir el canal.")

async def e_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Elimina un canal de la lista de publicación automática."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Solo el administrador puede usar este comando.")
        return
    
    if not context.args:
        await update.message.reply_text("Uso: /E @username_canal")
        return
    
    username = context.args[0].replace('@', '')
    
    success = await auto_post_manager.remove_channel(username)
    if success:
        await update.message.reply_text(f"✅ Canal @{username} eliminado de la lista de publicación automática.")
    else:
        await update.message.reply_text("❌ Error al eliminar el canal.")

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la lista de canales para publicación automática."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Solo el administrador puede usar este comando.")
        return
    
    channels = await auto_post_manager.get_channels()
    
    if not channels:
        await update.message.reply_text("No hay canales en la lista de publicación automática.")
        return
    
    text = "📋 **Canales de Publicación Automática:**\n\n"
    for i, channel in enumerate(channels, 1):
        text += f"{i}. @{channel['username']}\n"
    
    await update.message.reply_text(text)

async def v_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verifica permisos en todos los canales."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Solo el administrador puede usar este comando.")
        return
    
    channels = await auto_post_manager.get_channels()
    report = "🔍 **Informe de Verificación de Canales:**\n\n"
    
    for channel in channels:
        try:
            chat = await context.bot.get_chat(f"@{channel['username']}")
            bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
            
            if bot_member.status in ['administrator', 'creator']:
                perms = bot_member.can_post_messages and bot_member.can_edit_messages and bot_member.can_delete_messages
                status = "✅ Permisos correctos" if perms else "⚠️ Permisos insuficientes"
            else:
                status = "❌ No es administrador"
            
            report += f"• @{channel['username']}: {status}\n"
            
        except Exception as e:
            report += f"• @{channel['username']}: ❌ Error - {str(e)}\n"
    
    await update.message.reply_text(report)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Maneja todos los mensajes."""
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Verificar si el usuario está silenciado
    if user_id in muted_users:
        mute_info = muted_users[user_id]
        if datetime.now() < mute_info["until"]:
            try:
                await update.message.delete()
                return
            except:
                pass
        else:
            del muted_users[user_id]
    
    # Verificar spam
    if check_spam(user_id) and not await is_admin(user_id, chat_id, context):
        try:
            permissions = ChatPermissions(can_send_messages=False)
            until_date = datetime.now() + timedelta(seconds=SPAM_MUTE_TIME)
            
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=permissions,
                until_date=until_date
            )
            
            muted_users[user_id] = {
                "until": until_date,
                "reason": "Spam detectado"
            }
            
            await update.message.reply_html(
                f"🔇 {update.effective_user.mention_html()} ha sido silenciado por {format_time_delta(SPAM_MUTE_TIME)} por enviar mensajes demasiado rápido."
            )
            
            try:
                await update.message.delete()
            except:
                pass
            
            return
        except:
            pass
    
    # Procesar solicitud de canal si corresponde
    if update.message and update.message.text and "#" in update.message.text:
        await process_channel_submission(update, context)
    
    # Actualizar estadísticas
    if update.message:
        if update.message.photo or update.message.video or update.message.document or update.message.animation:
            await db.update_user_stats(user_id, chat_id, "media")
        else:
            await db.update_user_stats(user_id, chat_id, "messages")
    
    user_last_activity[user_id] = datetime.now()

def main() -> None:
    """Inicia el bot."""
    global auto_post_manager
    
    # Inicializar administrador de posts automáticos
    auto_post_manager = AutoPostManager(db)
    
    # Crear la aplicación
    application = Application.builder().token(TOKEN).build()
    
    # Registrar manejadores
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("MisCanales", miscanales_command))
    application.add_handler(CommandHandler("del", del_command))
    application.add_handler(CommandHandler("edit", edit_command))
    application.add_handler(CommandHandler("A", a_command))
    application.add_handler(CommandHandler("E", e_command))
    application.add_handler(CommandHandler("List", list_command))
    application.add_handler(CommandHandler("V", v_command))
    
    # Otros manejadores
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_message))
    
    # Ejecutar el bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
