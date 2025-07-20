from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
import os
from typing import List
from typing import Optional


router = APIRouter()

# MongoDB setup
client = AsyncIOMotorClient(os.getenv("MONGO_URI"))
db = client["rojgar"]
Device = db["devices"]
CenterBoard = db["centerboard"]
StateBoard = db["state"]

# Pydantic schema
class RegisterDeviceModel(BaseModel):
    deviceId: str
    name: str = None
    brand: str = None
    model: str = None
    expoPushToken: str = None
    preferences: Optional[List[str]] = None  

@router.post("/register-device")
async def register_device(data: RegisterDeviceModel):
    print("📥 Incoming device registration:", data.dict())

    if not data.deviceId:
        print("❌ Device ID is missing")
        raise HTTPException(status_code=400, detail="Device ID is required")

    try:
        existing = await Device.find_one({"deviceId": data.deviceId})

        if not existing:
            new_device_data = {
                "deviceId": data.deviceId,
                "name": data.name,
                "brand": data.brand,
                "model": data.model,
                "expoPushToken": data.expoPushToken,
                "status": "active",
                "role": "user"
            }

            if data.preferences:
                new_device_data["preferences"] = data.preferences

            result = await Device.insert_one(new_device_data)
            print("✅ Device registered:", result.inserted_id)
            return {"status": "registered"}

        else:
            print("ℹ️ Device already exists:", existing)

            if data.preferences and not existing.get("preferences"):
                await Device.update_one(
                    {"deviceId": data.deviceId},
                    {"$set": {"preferences": data.preferences}}
                )
                print("🔄 Preferences updated for existing device")

            return {"status": "already exists"}

    except Exception as e:
        print("❌ Error in /register-device:", str(e))
        raise HTTPException(status_code=500, detail="Server error")


# 📤 Fetch board data from centerboard and state
@router.get("/boards")
async def get_boards():
    try:
        center_cursor = CenterBoard.find({}, {"_id": 0})
        state_cursor = StateBoard.find({}, {"_id": 0})

        center_boards = await center_cursor.to_list(length=100)
        state_boards = await state_cursor.to_list(length=100)

        return {
            "centerBoards": center_boards,
            "stateBoards": state_boards
        }

    except Exception as e:
        print("❌ Error fetching board data:", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch board data")
