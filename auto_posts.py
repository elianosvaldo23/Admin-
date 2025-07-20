import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

class AutoPostManager:
    def __init__(self, database):
        self.db = database
        self.bot = None
        self.admin_id = None
        self.categories = {}
        self.active_posts = {}
        self.scheduled_tasks = {}
    
    def set_bot(self, bot: Bot, admin_id: int, categories: Dict):
        """Configura el bot y parámetros necesarios."""
        self.bot = bot
        self.admin_id = admin_id
        self.categories = categories
    
    async def add_channel(self, username: str) -> bool:
        """Añade un canal a la lista de publicación automática."""
        try:
            channel_data = {
                "username": username,
                "added_date": datetime.now(),
                "active": True,
                "last_post": None,
                "post_count": 0,
                "error_count": 0
            }
            
            result = self.db.auto_post_channels.insert_one(channel_data)
            return result.inserted_id is not None
            
        except Exception as e:
            logger.error(f"Error adding channel to auto post: {e}")
            return False
    
    async def remove_channel(self, username: str) -> bool:
        """Elimina un canal de la lista de publicación automática."""
        try:
            result = self.db.auto_post_channels.delete_one({"username": username})
            return result.deleted_count > 0
            
        except Exception as e:
            logger.error(f"Error removing channel from auto post: {e}")
            return False
    
    async def get_channels(self) -> List[Dict]:
        """Obtiene todos los canales de publicación automática."""
        try:
            channels = list(self.db.auto_post_channels.find({"active": True}))
            for channel in channels:
                channel["_id"] = str(channel["_id"])
            return channels
            
        except Exception as e:
            logger.error(f"Error getting auto post channels: {e}")
            return []
    
    async def create_post(self, post_data: Dict) -> bool:
        """Crea una nueva publicación automática."""
        try:
            post_data["created_date"] = datetime.now()
            post_data["status"] = "scheduled"
            post_data["sent_channels"] = []
            post_data["failed_channels"] = []
            post_data["statistics"] = {
                "total_sent": 0,
                "total_failed": 0,
                "user_interactions": {}
            }
            
            result = self.db.auto_posts.insert_one(post_data)
            
            if result.inserted_id:
                # Programar la publicación
                await self.schedule_post(str(result.inserted_id), post_data)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error creating auto post: {e}")
            return False
    
    async def schedule_post(self, post_id: str, post_data: Dict):
        """Programa una publicación para ser enviada."""
        try:
            publish_time = post_data.get("publish_time")
            if not publish_time:
                return
            
            # Calcular tiempo hasta la publicación
            now = datetime.now()
            if publish_time > now:
                delay = (publish_time - now).total_seconds()
                
                # Programar tarea
                task = asyncio.create_task(self._delayed_post(post_id, delay))
                self.scheduled_tasks[post_id] = task
            else:
                # Publicar inmediatamente
                await self.send_post(post_id)
                
        except Exception as e:
            logger.error(f"Error scheduling post: {e}")
    
    async def _delayed_post(self, post_id: str, delay: float):
        """Espera y luego publica un post."""
        try:
            await asyncio.sleep(delay)
            await self.send_post(post_id)
        except asyncio.CancelledError:
            logger.info(f"Post {post_id} was cancelled")
        except Exception as e:
            logger.error(f"Error in delayed post: {e}")
    
    async def send_post(self, post_id: str) -> Dict:
        """Envía una publicación a todos los canales."""
        try:
            from bson import ObjectId
            post = self.db.auto_posts.find_one({"_id": ObjectId(post_id)})
            if not post:
                return {"success": False, "error": "Post not found"}
            
            channels = await self.get_channels()
            sent_count = 0
            failed_count = 0
            sent_channels = []
            failed_channels = []
            
            # Crear botones inline con categorías
            keyboard = []
            row = []
            for i, (category, url) in enumerate(self.categories.items()):
                row.append(InlineKeyboardButton(category, url=url))
                if (i + 1) % 2 == 0 or i == len(self.categories) - 1:
                    keyboard.append(row)
                    row = []
            
            # Añadir botones personalizados si existen
            custom_buttons = post.get("custom_buttons", [])
            for button_row in custom_buttons:
                keyboard.append([
                    InlineKeyboardButton(btn["text"], url=btn["url"]) 
                    for btn in button_row
                ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Enviar a cada canal
            for channel in channels:
                try:
                    if post.get("image_path"):
                        # Enviar con imagen
                        with open(post["image_path"], 'rb') as photo:
                            message = await self.bot.send_photo(
                                chat_id=f"@{channel['username']}",
                                photo=photo,
                                caption=post.get("text", ""),
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                    else:
                        # Enviar solo texto
                        message = await self.bot.send_message(
                            chat_id=f"@{channel['username']}",
                            text=post.get("text", ""),
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup
                        )
                    
                    sent_count += 1
                    sent_channels.append({
                        "channel": channel['username'],
                        "message_id": message.message_id,
                        "sent_time": datetime.now()
                    })
                    
                    # Actualizar estadísticas del canal
                    self.db.auto_post_channels.update_one(
                        {"username": channel['username']},
                        {
                            "$set": {"last_post": datetime.now()},
                            "$inc": {"post_count": 1}
                        }
                    )
                    
                except TelegramError as e:
                    failed_count += 1
                    failed_channels.append({
                        "channel": channel['username'],
                        "error": str(e),
                        "failed_time": datetime.now()
                    })
                    
                    # Incrementar contador de errores
                    self.db.auto_post_channels.update_one(
                        {"username": channel['username']},
                        {"$inc": {"error_count": 1}}
                    )
                    
                    logger.error(f"Error sending to {channel['username']}: {e}")
            
            # Actualizar post con resultados
            self.db.auto_posts.update_one(
                {"_id": ObjectId(post_id)},
                {
                    "$set": {
                        "status": "sent",
                        "sent_time": datetime.now(),
                        "sent_channels": sent_channels,
                        "failed_channels": failed_channels,
                        "statistics.total_sent": sent_count,
                        "statistics.total_failed": failed_count
                    }
                }
            )
            
            # Notificar al administrador
            if self.bot and self.admin_id:
                await self._notify_admin_post_result(post_id, sent_count, failed_count, sent_channels, failed_channels)
            
            # Programar eliminación si está configurada
            if post.get("delete_after_hours"):
                delete_time = datetime.now() + timedelta(hours=post["delete_after_hours"])
                asyncio.create_task(self._schedule_deletion(post_id, delete_time))
            
            return {
                "success": True,
                "sent_count": sent_count,
                "failed_count": failed_count,
                "sent_channels": sent_channels,
                "failed_channels": failed_channels
            }
            
        except Exception as e:
            logger.error(f"Error sending post: {e}")
            return {"success": False, "error": str(e)}
    
    async def _notify_admin_post_result(self, post_id: str, sent_count: int, failed_count: int, sent_channels: List, failed_channels: List):
        """Notifica al administrador sobre el resultado de la publicación."""
        try:
            message = (
                f"📊 **Resultado de Publicación**\n\n"
                f"🆔 Post ID: {post_id}\n"
                f"✅ Enviado exitosamente: {sent_count} canales\n"
                f"❌ Fallos: {failed_count} canales\n"
                f"🕒 Hora: {datetime.now().strftime('%H:%M:%S')}\n\n"
            )
            
            if failed_channels:
                message += "**Canales con errores:**\n"
                for failed in failed_channels[:5]:  # Mostrar solo los primeros 5
                    message += f"• @{failed['channel']}: {failed['error']}\n"
                if len(failed_channels) > 5:
                    message += f"... y {len(failed_channels) - 5} más\n"
            
            await self.bot.send_message(
                chat_id=self.admin_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Error notifying admin: {e}")
    
    async def _schedule_deletion(self, post_id: str, delete_time: datetime):
        """Programa la eliminación de un post."""
        try:
            now = datetime.now()
            if delete_time > now:
                delay = (delete_time - now).total_seconds()
                await asyncio.sleep(delay)
            
            await self.delete_post(post_id)
            
        except Exception as e:
            logger.error(f"Error scheduling deletion: {e}")
    
    async def delete_post(self, post_id: str) -> Dict:
        """Elimina una publicación de todos los canales."""
        try:
            from bson import ObjectId
            post = self.db.auto_posts.find_one({"_id": ObjectId(post_id)})
            if not post:
                return {"success": False, "error": "Post not found"}
            
            sent_channels = post.get("sent_channels", [])
            deleted_count = 0
            failed_deletions = []
            
            for channel_info in sent_channels:
                try:
                    await self.bot.delete_message(
                        chat_id=f"@{channel_info['channel']}",
                        message_id=channel_info['message_id']
                    )
                    deleted_count += 1
                    
                except TelegramError as e:
                    failed_deletions.append({
                        "channel": channel_info['channel'],
                        "error": str(e)
                    })
                    logger.error(f"Error deleting from {channel_info['channel']}: {e}")
            
            # Actualizar estado del post
            self.db.auto_posts.update_one(
                {"_id": ObjectId(post_id)},
                {
                    "$set": {
                        "status": "deleted",
                        "deleted_time": datetime.now(),
                        "deleted_count": deleted_count,
                        "failed_deletions": failed_deletions
                    }
                }
            )
            
            # Notificar al administrador
            if self.bot and self.admin_id:
                await self._notify_admin_deletion_result(post_id, deleted_count, len(failed_deletions))
            
            return {
                "success": True,
                "deleted_count": deleted_count,
                "failed_count": len(failed_deletions)
            }
            
        except Exception as e:
            logger.error(f"Error deleting post: {e}")
            return {"success": False, "error": str(e)}
    
    async def _notify_admin_deletion_result(self, post_id: str, deleted_count: int, failed_count: int):
        """Notifica al administrador sobre el resultado de la eliminación."""
        try:
            message = (
                f"🗑️ **Resultado de Eliminación**\n\n"
                f"🆔 Post ID: {post_id}\n"
                f"✅ Eliminado exitosamente: {deleted_count} canales\n"
                f"❌ Fallos: {failed_count} canales\n"
                f"🕒 Hora: {datetime.now().strftime('%H:%M:%S')}"
            )
            
            await self.bot.send_message(
                chat_id=self.admin_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Error notifying admin about deletion: {e}")
    
    async def get_post_statistics(self, post_id: str) -> Dict:
        """Obtiene estadísticas de una publicación."""
        try:
            from bson import ObjectId
            post = self.db.auto_posts.find_one({"_id": ObjectId(post_id)})
            if not post:
                return {"success": False, "error": "Post not found"}
            
            return {
                "success": True,
                "statistics": post.get("statistics", {}),
                "sent_channels": len(post.get("sent_channels", [])),
                "failed_channels": len(post.get("failed_channels", [])),
                "status": post.get("status"),
                "created_date": post.get("created_date"),
                "sent_time": post.get("sent_time"),
                "deleted_time": post.get("deleted_time")
            }
            
        except Exception as e:
            logger.error(f"Error getting post statistics: {e}")
            return {"success": False, "error": str(e)}
