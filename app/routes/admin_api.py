from fastapi import APIRouter, Request, Query, HTTPException, Depends
from pydantic import BaseModel
from bs4 import BeautifulSoup
import requests
import os
from datetime import datetime
from app.deps.auth import verify_api_key
from app.core.scraper import scrape_and_update
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from bson import ObjectId
from typing import List


load_dotenv()

router = APIRouter(dependencies=[Depends(verify_api_key)])

# MongoDB setup
client = AsyncIOMotorClient(os.getenv("MONGO_URI"))
db = client["rojgar"]
Device = db["devices"]
Scrapeed = db["Scrapeed"]
Post = db["posts"]

# Env secret
SECRET_KEY = os.getenv("SECRET_KEY", "demo-key")


# ---------- MODELS ----------
class PostModel(BaseModel):
    title: str
    sup: str
    url: str
    preferences: List[str]
    category: str
    content: str


class SearchModel(BaseModel):
    keyword: str = ""


# ---------- ADMIN UTILS ----------
@router.get("/admin/api/posts")
async def get_posts():
    cursor = Scrapeed.find(
        {"posted": "No"},
        {
            "title": 1,
            "url": 1,
            "section": 1,
            "sup": 1,
            "order_no": 1,
            "posted": 1,
            "updated_at": 1,
            "_id": 1
        }
    ).sort("updated_at", -1)

    posts = await cursor.to_list(length=100)

    for post in posts:
        if "_id" in post and isinstance(post["_id"], ObjectId):
            post["_id"] = str(post["_id"])

    return posts



EXPO_API_URL = "https://exp.host/--/api/v2/push/send"

def send_push_notification(tokens: List[str], title: str, body: str):
    messages = [{"to": token, "title": title, "body": body} for token in tokens]

    for i in range(0, len(messages), 100):
        chunk = messages[i:i + 100]
        print("📦 Sending chunk:", chunk)  # <-- Add this

        try:
            response = requests.post(EXPO_API_URL, json=chunk)
            print("📨 Expo response:", response.status_code, response.text)  # <-- Add this

            if response.status_code != 200:
                print("❌ Expo push failed:", response.text)

        except Exception as e:
            print("🔥 Error sending push:", str(e))


@router.post("/admin/api/search-posts")
async def search_posts(data: SearchModel):
    query = {"title": {"$regex": data.keyword, "$options": "i"}} if data.keyword else {}

    cursor = Post.find(
        query,
        {
            "title": 1,
            "url": 1,
            "category": 1,
            "sup": 1,
            "updatedAt": 1,
            "_id": 1
        }
    ).sort("updatedAt", -1)

    posts = await cursor.to_list(length=20 if data.keyword else 10)

    for post in posts:
        if "_id" in post and isinstance(post["_id"], ObjectId):
            post["_id"] = str(post["_id"])

    return {"posts": posts}


@router.post("/admin/api/add-posts")
async def add_or_update_post(data: PostModel):
    SPECIAL_URLS = ["Admitcard_more.html", "latestresult_more.html", "answerkey_more.html"]
    is_special = any(s in data.url for s in SPECIAL_URLS)
    is_external = "resultbharat.com" not in data.url
    use_title = is_special and not is_external

    match_field = "title" if use_title else "url"
    match_value = data.title if use_title else data.url

    query = {match_field: match_value}
    post = await Post.find_one(query)

    now = datetime.utcnow()

    if post:
        update_data = data.dict()
        update_data["updatedAt"] = now
        await Post.update_one(query, {"$set": update_data})
        msg = "✅ Post updated"
    else:
        insert_data = data.dict()
        insert_data["createdAt"] = now
        insert_data["updatedAt"] = now
        await Post.insert_one(insert_data)
        msg = "✅ Post created"

    updated = await Scrapeed.find_one_and_update(
        {"title": data.title.strip()},
        {"$set": {"posted": "Yes"}},
        return_document=True
    )

    if not updated:
        await Scrapeed.find_one_and_update(
            {"title": {"$regex": f"^{data.title.strip()}$", "$options": "i"}},
            {"$set": {"posted": "Yes"}}
        )

    # ✅ Send Notification
    post_preferences = data.preferences or []

    if post_preferences:
        filter_query = {
            "role": "user",
            "$or": [
                {"preferences": {"$in": post_preferences}},
                {"preferences": {"$size": 0}},
                {"preferences": {"$exists": False}}
            ]
        }
    else:
        filter_query = {"role": "user"}

    user_devices = await Device.find(filter_query).to_list(None)
    push_tokens = [u.get("expoPushToken") for u in user_devices if u.get("expoPushToken")]

    notif_title = data.title
    if data.category.strip().lower().replace(" ", "") == "latestjobs":
        notif_body = f"Apply now — {data.sup}"
    else:
        notif_body = f"Check now — {data.sup}"

    if push_tokens:
        try:
            print("📱 Sending to tokens:", push_tokens)
            send_push_notification(
                push_tokens,
                title=notif_title,
                body=notif_body
            )
            print("✅ Push sent.")
        except Exception as e:
            print("❌ Error sending push notification:")
            print(str(e))
          

    return {"success": True, "message": msg, "post": data.dict()}

@router.get("/admin/api/scrape-for-tr")
def scrape_for_tr(url: str = Query(..., description="URL to scrape")):
    try:
        response = requests.get(url)
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        main_table = soup.find("table")
        if not main_table:
            return {"rows": []}
        trs = main_table.find_all("tr")
        rows = [str(tr) for tr in trs]
        return {"rows": rows}
    except Exception as e:
        return {"error": str(e)}


@router.post("/admin/api/beautify")
async def beautify_html(request: Request):
    data = await request.json()
    raw_html = data.get("content", "")
    soup = BeautifulSoup(f"<div>{raw_html}</div>", "html.parser")

    for script in soup.find_all("script"):
        script.decompose()

    for tag in soup.find_all(style=True):
        normalized_style = tag['style'].lower().replace(" ", "")
        if tag.name == "table" or "color:#ff0000" in normalized_style:
            continue
        del tag['style']

    for i in range(1, 8):
        color = "#4682b4" if i in [1, 2] else "#4caf50"
        for tag in soup.find_all(f"h{i}"):
            style = tag.get("style", "").lower().replace(" ", "")
            if "color:#ff0000" in style or "color:rgb(255,0,0)" in style:
                continue
            tag['style'] = f"text-align: center; color: {color};"

    for tag in soup.find_all(['p', 'div', 'span', 'strong', 'em', 'b', 'i']):
        if tag.find_parent(['ul', 'li']):
            continue
        style = tag.get("style", "").lower().replace(" ", "")
        if "color:#ff0000" in style:
            continue
        tag['style'] = "text-align: center;"

    for tr in soup.find_all('tr'):
        tr['style'] = "border: 1px solid #ccc;"
        tds = tr.find_all('td')
        if len(tds) >= 2:
            width = f"{100 // len(tds)}%"
            for td in tds:
                td['width'] = width
        for td in tds:
            td['style'] = "border: 1px solid #ccc; padding: 8px;"

    inner_html = str(soup.find("div"))
    wrapped_html = f"""
    <table style="width: 100%;">
        <tr>
            <td>{inner_html}</td>
        </tr>
    </table>
    """

    return {"beautified": wrapped_html}


@router.get("/admin/api/scrape")
def trigger_scraper(request: Request):
    key = request.query_params.get("key")
    if key != SECRET_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid key")

    result = scrape_and_update()
    return {"status": "ok", "result": result}
