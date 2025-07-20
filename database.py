import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import json

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        # Configuración de MongoDB
        self.mongo_uri = os.getenv("MONGODB_URI", "mongodb+srv://zoobot:zoobot@zoolbot.6avd6qf.mongodb.net/zoolbot?retryWrites=true&w=majority&appName=Zoolbot")
        self.db_name = os.getenv("DB_NAME", "zoolbot")
        
        try:
            self.client = MongoClient(self.mongo_uri)
            self.db = self.client[self.db_name]
            
            # Crear colecciones si no existen
            self.approved_channels = self.db.approved_channels
            self.pending_submissions = self.db.pending_submissions
            self.user_stats = self.db.user_stats
            self.warnings = self.db.warnings
            self.config = self.db.config
            self.auto_post_channels = self.db.auto_post_channels
            self.auto_posts = self.db.auto_posts
            
            # Crear índices
            self.approved_channels.create_index("channel_username", unique=True)
            self.approved_channels.create_index("added_by")
            self.approved_channels.create_index("category")
            self.pending_submissions.create_index("submission_id", unique=True)
            self.user_stats.create_index([("user_id", 1), ("chat_id", 1)], unique=True)
            self.warnings.create_index([("user_id", 1), ("chat_id", 1)], unique=True)
            
            logger.info("Conexión a MongoDB establecida exitosamente")
            
        except Exception as e:
            logger.error(f"Error conectando a MongoDB: {e}")
            raise
    
    async def save_approved_channel(self, channel_id: str, channel_name: str, 
                                  channel_username: str, category: str, 
                                  added_by: int, channel_link: str = None) -> bool:
        """Guarda un canal aprobado en la base de datos."""
        try:
            channel_data = {
                "channel_id": channel_id,
                "channel_name": channel_name,
                "channel_username": channel_username,
                "category": category,
                "added_by": added_by,
                "channel_link": channel_link or f"https://t.me/{channel_username}",
                "added_date": datetime.now(),
                "subscriber_count": 0,
                "last_updated": datetime.now()
            }
            
            result = self.approved_channels.insert_one(channel_data)
            return result.inserted_id is not None
            
        except PyMongoError as e:
            logger.error(f"Error saving approved channel: {e}")
            return False
    
    async def get_approved_channels(self, category: str = None) -> List[Dict]:
        """Obtiene los canales aprobados, opcionalmente filtrados por categoría."""
        try:
            filter_query = {"category": category} if category else {}
            channels = list(self.approved_channels.find(filter_query).sort("added_date", 1))
            
            # Convertir ObjectId a string para serialización
            for channel in channels:
                channel["_id"] = str(channel["_id"])
            
            return channels
            
        except PyMongoError as e:
            logger.error(f"Error getting approved channels: {e}")
            return []
    
    async def get_user_channels(self, user_id: int) -> List[Dict]:
        """Obtiene todos los canales añadidos por un usuario específico."""
        try:
            channels = list(self.approved_channels.find({"added_by": user_id}).sort("added_date", 1))
            
            for channel in channels:
                channel["_id"] = str(channel["_id"])
            
            return channels
            
        except PyMongoError as e:
            logger.error(f"Error getting user channels: {e}")
            return []
    
    async def get_channel_by_username(self, username: str) -> Optional[Dict]:
        """Obtiene un canal por su nombre de usuario."""
        try:
            channel = self.approved_channels.find_one({"channel_username": username})
            if channel:
                channel["_id"] = str(channel["_id"])
            return channel
            
        except PyMongoError as e:
            logger.error(f"Error getting channel by username: {e}")
            return None
    
    async def get_channel_by_id(self, channel_id: str) -> Optional[Dict]:
        """Obtiene un canal por su ID."""
        try:
            from bson import ObjectId
            channel = self.approved_channels.find_one({"_id": ObjectId(channel_id)})
            if channel:
                channel["_id"] = str(channel["_id"])
            return channel
            
        except PyMongoError as e:
            logger.error(f"Error getting channel by ID: {e}")
            return None
    
    async def delete_channel(self, channel_id: str) -> bool:
        """Elimina un canal de la base de datos."""
        try:
            from bson import ObjectId
            result = self.approved_channels.delete_one({"_id": ObjectId(channel_id)})
            return result.deleted_count > 0
            
        except PyMongoError as e:
            logger.error(f"Error deleting channel: {e}")
            return False
    
    async def update_channel(self, channel_id: str, update_data: Dict) -> bool:
        """Actualiza un canal en la base de datos."""
        try:
            from bson import ObjectId
            update_data["last_updated"] = datetime.now()
            result = self.approved_channels.update_one(
                {"_id": ObjectId(channel_id)}, 
                {"$set": update_data}
            )
            return result.modified_count > 0
            
        except PyMongoError as e:
            logger.error(f"Error updating channel: {e}")
            return False
    
    async def save_pending_submission(self, submission_id: str, submission_data: Dict) -> bool:
        """Guarda una solicitud pendiente."""
        try:
            submission_data["submission_id"] = submission_id
            submission_data["submission_date"] = datetime.now()
            
            result = self.pending_submissions.insert_one(submission_data)
            return result.inserted_id is not None
            
        except PyMongoError as e:
            logger.error(f"Error saving pending submission: {e}")
            return False
    
    async def delete_pending_submission(self, submission_id: str) -> bool:
        """Elimina una solicitud pendiente."""
        try:
            result = self.pending_submissions.delete_one({"submission_id": submission_id})
            return result.deleted_count > 0
            
        except PyMongoError as e:
            logger.error(f"Error deleting pending submission: {e}")
            return False
    
    async def update_user_stats(self, user_id: int, chat_id: int, stat_type: str) -> bool:
        """Actualiza las estadísticas de un usuario."""
        try:
            now = datetime.now()
            
            self.user_stats.update_one(
                {"user_id": user_id, "chat_id": chat_id},
                {
                    "$inc": {stat_type: 1},
                    "$set": {"last_active": now}
                },
                upsert=True
            )
            return True
            
        except PyMongoError as e:
            logger.error(f"Error updating user stats: {e}")
            return False
    
    async def get_user_stats(self, user_id: int, chat_id: int) -> Dict:
        """Obtiene las estadísticas de un usuario."""
        try:
            stats = self.user_stats.find_one({"user_id": user_id, "chat_id": chat_id})
            
            if stats:
                return {
                    "messages": stats.get("messages", 0),
                    "media": stats.get("media", 0),
                    "commands": stats.get("commands", 0),
                    "last_active": stats.get("last_active")
                }
            else:
                return {
                    "messages": 0,
                    "media": 0,
                    "commands": 0,
                    "last_active": None
                }
                
        except PyMongoError as e:
            logger.error(f"Error getting user stats: {e}")
            return {"messages": 0, "media": 0, "commands": 0, "last_active": None}
    
    async def add_warning(self, user_id: int, chat_id: int, reason: str) -> int:
        """Añade una advertencia a un usuario."""
        try:
            warning_data = {
                "reason": reason,
                "date": datetime.now()
            }
            
            result = self.warnings.update_one(
                {"user_id": user_id, "chat_id": chat_id},
                {
                    "$inc": {"count": 1},
                    "$push": {"reasons": warning_data}
                },
                upsert=True
            )
            
            # Obtener el conteo actual
            warning_doc = self.warnings.find_one({"user_id": user_id, "chat_id": chat_id})
            return warning_doc.get("count", 1) if warning_doc else 1
            
        except PyMongoError as e:
            logger.error(f"Error adding warning: {e}")
            return 0
    
    async def get_warnings(self, user_id: int, chat_id: int) -> Dict:
        """Obtiene las advertencias de un usuario."""
        try:
            warnings = self.warnings.find_one({"user_id": user_id, "chat_id": chat_id})
            
            if warnings:
                return {
                    "count": warnings.get("count", 0),
                    "reasons": warnings.get("reasons", [])
                }
            else:
                return {"count": 0, "reasons": []}
                
        except PyMongoError as e:
            logger.error(f"Error getting warnings: {e}")
            return {"count": 0, "reasons": []}
    
    async def reset_warnings(self, user_id: int, chat_id: int) -> bool:
        """Reinicia las advertencias de un usuario."""
        try:
            result = self.warnings.delete_one({"user_id": user_id, "chat_id": chat_id})
            return result.deleted_count > 0
            
        except PyMongoError as e:
            logger.error(f"Error resetting warnings: {e}")
            return False
