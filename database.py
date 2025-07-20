import logging
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from config import MONGO_URI, DEFAULT_WELCOME_MESSAGE

# Configuración del logger
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class MongoDB:
    def __init__(self):
        self.client = None
        self.db = None
        self.connect()
        self.init_db()

    def connect(self):
        """Crea la conexión a MongoDB."""
        try:
            self.client = MongoClient(MONGO_URI)
            self.db = self.client.zoolbot  # Changed to match your DB name
            logger.info("Conexión a MongoDB establecida correctamente")
        except PyMongoError as e:
            logger.error(f"Error al conectar con MongoDB: {e}")
            raise

    def init_db(self):
        """Inicializa las colecciones de la base de datos."""
        try:
            # Crear índices necesarios
            self.db.approved_channels.create_index("channel_id", unique=True)
            self.db.approved_channels.create_index("channel_username")
            self.db.approved_channels.create_index("added_by")
            self.db.approved_channels.create_index("category")
            
            self.db.pending_submissions.create_index("submission_id", unique=True)
            self.db.pending_submissions.create_index("user_id")
            
            self.db.warnings.create_index([("user_id", 1), ("chat_id", 1)], unique=True)
            self.db.stats.create_index([("user_id", 1), ("chat_id", 1)], unique=True)
            
            self.db.auto_post_channels.create_index("channel_id", unique=True)
            
            # Nuevos índices para las nuevas funcionalidades
            self.db.user_channels.create_index([("channel_id", 1), ("owner_id", 1)], unique=True)
            self.db.scheduled_posts.create_index("post_id", unique=True)
            self.db.post_stats.create_index([("post_id", 1), ("channel_id", 1)], unique=True)
            
            # Verificar configuración inicial
            if not self.db.config.find_one({"key": "welcome_message"}):
                self.db.config.insert_one({
                    "key": "welcome_message",
                    "value": DEFAULT_WELCOME_MESSAGE
                })
            
            if not self.db.config.find_one({"key": "welcome_buttons"}):
                default_buttons = [
                    {"text": "Canal Principal", "url": "https://t.me/botoneraMultimediaTv"},
                    {"text": "Categorías", "url": "https://t.me/c/2259108243/2"},
                    {"text": "📣 Canales y Grupos 👥", "callback_data": "user_channels"}
                ]
                self.db.config.insert_one({
                    "key": "welcome_buttons",
                    "value": default_buttons
                })
            
            logger.info("Base de datos inicializada correctamente")
        except PyMongoError as e:
            logger.error(f"Error al inicializar la base de datos: {e}")
            raise

    # ----- FUNCIONES DE CONFIGURACIÓN -----
    def save_config(self, key, value):
        """Guarda un valor en la configuración."""
        try:
            self.db.config.update_one(
                {"key": key},
                {"$set": {"value": value}},
                upsert=True
            )
            return True
        except PyMongoError as e:
            logger.error(f"Error guardando configuración {key}: {e}")
            return False

    def load_config(self, key):
        """Carga un valor de la configuración."""
        try:
            config = self.db.config.find_one({"key": key})
            return config["value"] if config else None
        except PyMongoError as e:
            logger.error(f"Error cargando configuración {key}: {e}")
            return None

    # ----- FUNCIONES DE CANALES APROBADOS -----
    def save_approved_channel(self, channel_id, channel_name, channel_username, category, added_by):
        """Guarda un canal aprobado en la base de datos."""
        try:
            self.db.approved_channels.update_one(
                {"channel_id": channel_id},
                {
                    "$set": {
                        "channel_name": channel_name,
                        "channel_username": channel_username,
                        "category": category,
                        "added_by": added_by,
                        "added_date": datetime.now().isoformat(),
                        "subscribers": 0
                    }
                },
                upsert=True
            )
            return True, self.db.approved_channels.count_documents({"category": category})
        except PyMongoError as e:
            logger.error(f"Error guardando canal aprobado: {e}")
            return False, 0

    def get_approved_channels(self, category=None, user_id=None):
        """Obtiene los canales aprobados, opcionalmente filtrados por categoría o usuario."""
        try:
            query = {}
            if category:
                query["category"] = category
            if user_id:
                query["added_by"] = user_id
            
            return list(self.db.approved_channels.find(query))
        except PyMongoError as e:
            logger.error(f"Error obteniendo canales aprobados: {e}")
            return []

    def delete_approved_channel(self, channel_id):
        """Elimina un canal aprobado de la base de datos."""
        try:
            result = self.db.approved_channels.delete_one({"channel_id": channel_id})
            return result.deleted_count > 0
        except PyMongoError as e:
            logger.error(f"Error eliminando canal aprobado: {e}")
            return False

    # ----- FUNCIONES DE SOLICITUDES PENDIENTES -----
    def save_pending_submission(self, submission_id, submission_data):
        """Guarda una solicitud pendiente en la base de datos."""
        try:
            submission_data["submission_date"] = datetime.now().isoformat()
            self.db.pending_submissions.update_one(
                {"submission_id": submission_id},
                {"$set": submission_data},
                upsert=True
            )
            return True
        except PyMongoError as e:
            logger.error(f"Error guardando solicitud pendiente: {e}")
            return False

    def get_pending_submissions(self):
        """Obtiene todas las solicitudes pendientes."""
        try:
            return {s["submission_id"]: s for s in self.db.pending_submissions.find({}, {'_id': 0})}
        except PyMongoError as e:
            logger.error(f"Error obteniendo solicitudes pendientes: {e}")
            return {}

    def delete_pending_submission(self, submission_id):
        """Elimina una solicitud pendiente."""
        try:
            result = self.db.pending_submissions.delete_one({"submission_id": submission_id})
            return result.deleted_count > 0
        except PyMongoError as e:
            logger.error(f"Error eliminando solicitud pendiente: {e}")
            return False

    # ----- FUNCIONES DE ESTADÍSTICAS -----
    def update_user_stats(self, user_id, chat_id, stat_type):
        """Actualiza las estadísticas de un usuario."""
        try:
            self.db.stats.update_one(
                {"user_id": user_id, "chat_id": chat_id},
                {
                    "$inc": {stat_type: 1},
                    "$set": {"last_active": datetime.now().isoformat()}
                },
                upsert=True
            )
            return True
        except PyMongoError as e:
            logger.error(f"Error actualizando estadísticas: {e}")
            return False

    def get_user_stats(self, user_id, chat_id):
        """Obtiene las estadísticas de un usuario."""
        try:
            stats = self.db.stats.find_one({"user_id": user_id, "chat_id": chat_id})
            return {
                "messages": stats.get("messages", 0),
                "media": stats.get("media", 0),
                "commands": stats.get("commands", 0),
                "last_active": stats.get("last_active") if stats else None
            }
        except PyMongoError as e:
            logger.error(f"Error obteniendo estadísticas: {e}")
            return {"messages": 0, "media": 0, "commands": 0, "last_active": None}

    # ----- FUNCIONES DE ADVERTENCIAS -----
    def add_warning(self, user_id, chat_id, reason):
        """Añade una advertencia a un usuario."""
        try:
            warning = {
                "reason": reason,
                "date": datetime.now().isoformat()
            }
            
            result = self.db.warnings.update_one(
                {"user_id": user_id, "chat_id": chat_id},
                {
                    "$inc": {"count": 1},
                    "$push": {"reasons": warning}
                },
                upsert=True
            )
            
            if result.upserted_id:
                return 1
            else:
                warnings = self.db.warnings.find_one({"user_id": user_id, "chat_id": chat_id})
                return warnings.get("count", 1)
        except PyMongoError as e:
            logger.error(f"Error añadiendo advertencia: {e}")
            return 0

    def get_warnings(self, user_id, chat_id):
        """Obtiene las advertencias de un usuario."""
        try:
            warnings = self.db.warnings.find_one({"user_id": user_id, "chat_id": chat_id})
            return {
                "count": warnings.get("count", 0),
                "reasons": warnings.get("reasons", [])
            } if warnings else {"count": 0, "reasons": []}
        except PyMongoError as e:
            logger.error(f"Error obteniendo advertencias: {e}")
            return {"count": 0, "reasons": []}

    def reset_warnings(self, user_id, chat_id):
        """Reinicia las advertencias de un usuario."""
        try:
            result = self.db.warnings.delete_one({"user_id": user_id, "chat_id": chat_id})
            return result.deleted_count > 0
        except PyMongoError as e:
            logger.error(f"Error reiniciando advertencias: {e}")
            return False

    # ----- NUEVAS FUNCIONES PARA CANALES DE USUARIO -----
    def get_user_channels(self, user_id):
        """Obtiene los canales y grupos de un usuario."""
        try:
            return list(self.db.user_channels.find({"owner_id": user_id}))
        except PyMongoError as e:
            logger.error(f"Error obteniendo canales del usuario: {e}")
            return []

    def save_user_channel(self, channel_data):
        """Guarda un canal o grupo de usuario."""
        try:
            channel_data["added_date"] = datetime.now().isoformat()
            self.db.user_channels.update_one(
                {"channel_id": channel_data["channel_id"]},
                {"$set": channel_data},
                upsert=True
            )
            return True
        except PyMongoError as e:
            logger.error(f"Error guardando canal de usuario: {e}")
            return False

    def update_channel_name(self, channel_id, new_name):
        """Actualiza el nombre de un canal."""
        try:
            result = self.db.user_channels.update_one(
                {"channel_id": channel_id},
                {"$set": {"title": new_name}}
            )
            return result.modified_count > 0
        except PyMongoError as e:
            logger.error(f"Error actualizando nombre del canal: {e}")
            return False

    def update_channel_link(self, channel_id, new_link):
        """Actualiza el enlace de un canal."""
        try:
            result = self.db.user_channels.update_one(
                {"channel_id": channel_id},
                {"$set": {"link": new_link}}
            )
            return result.modified_count > 0
        except PyMongoError as e:
            logger.error(f"Error actualizando enlace del canal: {e}")
            return False

    def delete_user_channel(self, channel_id, user_id):
        """Elimina un canal de usuario."""
        try:
            result = self.db.user_channels.delete_one({
                "channel_id": channel_id,
                "owner_id": user_id
            })
            return result.deleted_count > 0
        except PyMongoError as e:
            logger.error(f"Error eliminando canal de usuario: {e}")
            return False

    # ----- FUNCIONES PARA POSTS AUTOMÁTICOS -----
    def save_post_config(self, post_id, config_data):
        """Guarda la configuración de un post automático."""
        try:
            self.db.scheduled_posts.update_one(
                {"post_id": post_id},
                {"$set": config_data},
                upsert=True
            )
            return True
        except PyMongoError as e:
            logger.error(f"Error guardando configuración del post: {e}")
            return False

    def get_post_config(self, post_id=None):
        """Obtiene la configuración de posts automáticos."""
        try:
            if post_id:
                return self.db.scheduled_posts.find_one({"post_id": post_id})
            return list(self.db.scheduled_posts.find({}))
        except PyMongoError as e:
            logger.error(f"Error obteniendo configuración de posts: {e}")
            return None if post_id else []

    def update_post_stats(self, post_id, channel_id, status, message_id=None, deleted_at=None):
        """Actualiza las estadísticas de un post."""
        try:
            update_data = {
                "status": status,
                "updated_at": datetime.now().isoformat()
            }
            if message_id:
                update_data["message_id"] = message_id
            if deleted_at:
                update_data["deleted_at"] = deleted_at

            self.db.post_stats.update_one(
                {"post_id": post_id, "channel_id": channel_id},
                {"$set": update_data},
                upsert=True
            )
            return True
        except PyMongoError as e:
            logger.error(f"Error actualizando estadísticas del post: {e}")
            return False

    def count_channels_by_type(self, user_id):
        """Cuenta los canales por tipo de un usuario."""
        try:
            pipeline = [
                {"$match": {"owner_id": user_id}},
                {"$group": {
                    "_id": "$type",
                    "count": {"$sum": 1},
                    "total_members": {"$sum": "$members"}
                }}
            ]
            results = list(self.db.user_channels.aggregate(pipeline))
            counts = {"channels": 0, "groups": 0, "channel_members": 0, "group_members": 0}
            for result in results:
                if result["_id"] == "channel":
                    counts["channels"] = result["count"]
                    counts["channel_members"] = result["total_members"]
                elif result["_id"] == "group":
                    counts["groups"] = result["count"]
                    counts["group_members"] = result["total_members"]
            return counts
        except PyMongoError as e:
            logger.error(f"Error contando canales por tipo: {e}")
            return {"channels": 0, "groups": 0, "channel_members": 0, "group_members": 0}
