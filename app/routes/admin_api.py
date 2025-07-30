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

# --- MongoDB setup ---
client = AsyncIOMotorClient(os.getenv("MONGO_URI"))
db = client["rojgar"]
Device = db["devices"]
Scrapeed = db["Scrapeed"]
Post = db["posts"]

# --- Env secret ---
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
        try:
            response = requests.post(EXPO_API_URL, json=chunk)
            print("📨 Expo response:", response.status_code, response.text)
        except Exception as e:
            print("🔥 Error sending push:", str(e))

def send_telegram_post(title: str, sup: str, category: str, preferences: List[str]):
    from urllib.parse import quote

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
    APP_DOWNLOAD_URL = os.getenv("APP_DOWNLOAD_URL", "https://jobalertapk.netlify.app")

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("❌ Telegram config missing.")
        return

    base_tags = {"ResultBharat", "SarkariResult", "JobAlert"}
    if category:
        base_tags.add(category.strip().replace(" ", "").capitalize())
    for pref in preferences:
        if pref.strip():
            base_tags.add(pref.strip().replace(" ", "").capitalize())

    hashtags = " ".join(f"#{tag}" for tag in sorted(base_tags))

    message = f"""📢 <b>{title}</b> 🎤\n🗓️ {sup}\n\n{hashtags}\n\n🔗 <b>Download App:</b>\n👉 {APP_DOWNLOAD_URL}\n\n📲 इस जानकारी को शेयर करें और अपडेट रहें! ✅"""
    url_encoded_message = quote(message)
    telegram_api_url = (
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        f"?chat_id={TELEGRAM_CHANNEL_ID}&text={url_encoded_message}&parse_mode=HTML"
    )
    try:
        response = requests.get(telegram_api_url)
        print("📬 Telegram Response:", response.status_code, response.text)
    except Exception as e:
        print("🔥 Telegram post failed:", str(e))

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
        await Post.update_one(query, {"$set": {**data.dict(), "updatedAt": now}})
        msg = "✅ Post updated"
    else:
        await Post.insert_one({**data.dict(), "createdAt": now, "updatedAt": now})
        msg = "✅ Post created"

    await Scrapeed.find_one_and_update(
        {"title": data.title.strip()},
        {"$set": {"posted": "Yes"}},
        return_document=True
    ) or await Scrapeed.find_one_and_update(
        {"title": {"$regex": f"^{data.title.strip()}$", "$options": "i"}},
        {"$set": {"posted": "Yes"}}
    )

    filter_query = {
        "role": "user",
        "$or": [
            {"preferences": {"$in": data.preferences}},
            {"preferences": {"$size": 0}},
            {"preferences": {"$exists": False}}
        ]
    } if data.preferences else {"role": "user"}

    user_devices = await Device.find(filter_query).to_list(None)
    push_tokens = [u.get("expoPushToken") for u in user_devices if u.get("expoPushToken")]
    notif_title = data.title
    notif_body = f"Apply now — {data.sup}" if data.category.strip().lower().replace(" ", "") == "latestjobs" else f"Check now — {data.sup}"

    if push_tokens:
        send_push_notification(push_tokens, notif_title, notif_body)

    send_telegram_post(data.title, data.sup, data.category, data.preferences)
    return {"success": True, "message": msg, "post": data.dict()}

@router.get("/admin/api/scrape-for-tr")
def scrape_for_tr(url: str = Query(..., description="URL to scrape")):
    try:
        response = requests.get(url)
        response.encoding = "utf-8"
        soup = BeautifulSoup(response.text, "html.parser")
        main_table = soup.find("table")
        trs = main_table.find_all("tr") if main_table else []
        return {"rows": [str(tr) for tr in trs]}
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
        if tag.name != "table" and "color:#ff0000" not in tag['style'].lower().replace(" ", ""):
            del tag['style']

    for i in range(1, 8):
        color = "#4682b4" if i in [1, 2] else "#4caf50"
        for tag in soup.find_all(f"h{i}"):
            if "color:#ff0000" not in tag.get("style", "").lower():
                tag['style'] = f"text-align: center; color: {color};"

    for tag in soup.find_all(['p', 'div', 'span', 'strong', 'em', 'b', 'i']):
        if not tag.find_parent(['ul', 'li']) and "color:#ff0000" not in tag.get("style", "").lower():
            tag['style'] = "text-align: center;"

    for tr in soup.find_all('tr'):
        tr['style'] = "border: 1px solid #ccc;"
        tds = tr.find_all('td')
        width = f"{100 // len(tds)}%" if len(tds) >= 2 else "100%"
        for td in tds:
            td['width'] = width
            td['style'] = "border: 1px solid #ccc; padding: 8px;"

    inner_html = str(soup.find("div"))
    wrapped_html = f"""
    <table style=\"width: 100%;\">
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
    return {"status": "ok", "result": scrape_and_update()}
