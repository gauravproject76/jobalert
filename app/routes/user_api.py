from fastapi import APIRouter, Query, HTTPException, Depends
from typing import Optional, List
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
import os
import re
from app.deps.auth_user import verify_api_key_user
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(dependencies=[Depends(verify_api_key_user)])

# MongoDB setup
client = AsyncIOMotorClient(os.getenv("MONGO_URI"))
db = client["rojgar"]
Device = db["devices"]
Scrapeed = db["scrapeeds"]
Post = db["posts"]


# Pydantic model for response
class PostModel(BaseModel):
    title: Optional[str]
    url: Optional[str]
    content: Optional[str]
    updatedAt: Optional[str]
    category: Optional[str] = Field(None, example="jobs")


# 🔹 GET /posts — Get latest 20 posts, optionally filtered by category
@router.get("/posts", response_model=List[PostModel])
async def get_posts(category: Optional[str] = Query(None)):
    query = {}
    if category:
        query["category"] = category

    cursor = Post.find(query).sort("updatedAt", -1).limit(20)
    posts = await cursor.to_list(length=20)
    return posts


# 🔹 GET /search?q= — Search posts by title
@router.get("/search")
async def search_posts(q: Optional[str] = Query(None)):
    if q:
        query = {"title": {"$regex": re.escape(q), "$options": "i"}}
        limit = 100
    else:
        query = {}
        limit = 10

    cursor = Post.find(query).sort("_id", -1).limit(limit)
    posts = await cursor.to_list(length=limit)
    return {"posts": posts}


# 🔹 GET /view?title=...&url=... — View a single post by title or URL
@router.get("/view")
async def view_post(title: Optional[str] = None, url: Optional[str] = None):
    conditions = []
    if title:
        conditions.append({"title": title})
    if url:
        conditions.append({"url": url})

    if not conditions:
        raise HTTPException(status_code=400, detail="Either 'title' or 'url' must be provided")

    query = {"$or": conditions}
    post = await Post.find_one(query)

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    return {"content": post.get("content"), "title": post.get("title")}