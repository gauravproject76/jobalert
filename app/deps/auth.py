from fastapi import Header, HTTPException
from pymongo import MongoClient
import os
from dotenv import load_dotenv

# Load env variables
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client.get_default_database()
user_collection = db.devices

async def verify_api_key(x_api_key: str = Header(None)):
    if not x_api_key:
        raise HTTPException(status_code=403, detail="Forbidden on Home")

    user = user_collection.find_one({"deviceId": x_api_key, "status": "active", "role": "admin"})
    if not user:
        raise HTTPException(status_code=403, detail="Forbidden")

    return user
