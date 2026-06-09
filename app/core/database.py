from motor.motor_asyncio import AsyncIOMotorClient

from app.config import DB_NAME, MONGO_URL

client = AsyncIOMotorClient(MONGO_URL or "mongodb://localhost:27017")
db = client[DB_NAME]


async def ensure_indexes():
    await db.users.create_index("uid", unique=True)
    await db.users.create_index("username", unique=True)
    await db.users.create_index("firebase_uid", unique=True)
    await db.messages.create_index([("from_uid", 1), ("to_uid", 1), ("timestamp", -1)])
    await db.messages.create_index([("to_uid", 1), ("timestamp", -1)])
    await db.messages.create_index("attachment.file_id", sparse=True)
    await db.messages.create_index("message_id", unique=True, sparse=True)
    await db.connections.create_index([("uid_a", 1), ("uid_b", 1)], unique=True)
