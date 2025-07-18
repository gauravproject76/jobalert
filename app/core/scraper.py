import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pymongo import MongoClient, UpdateOne
from dotenv import load_dotenv
from datetime import datetime

# ✅ Load environment variables
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

# ✅ MongoDB setup
client = MongoClient(MONGO_URI)
db = client.get_default_database()
collection = db.Scrapeed
device_collection = db.devices

# ✅ Constants
BASE_URL = "https://www.resultbharat.com/"
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

TARGET_SECTIONS = {
    "Latest Jobs",
    "Answer Key",
    "Admit Card",
    "Results",
    "Admission"
}

SPECIAL_URLS = [
    "Admitcard_more.html",
    "latestresult_more.html",
    "answerkey_more.html"
]

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

def is_special_url(url: str) -> bool:
    return any(special in url for special in SPECIAL_URLS)

def send_push_to_admins(title, body):
    devices = list(device_collection.find({}))
    print("All devices in Device collection:", len(devices))

    admin_devices = list(device_collection.find({
        "role": "admin",
        "expoPushToken": { "$ne": None }
    }))
    
    print("Filtered admin devices:", len(admin_devices))

    for device in admin_devices:
        token = device.get("expoPushToken")
        print("Token:", token)

        if token:
            payload = {
                "to": token,
                "sound": "default",
                "title": title,
                "body": body,
                "data": { "screen": "AdminDashboard" }
            }
            try:
                response = requests.post(EXPO_PUSH_URL, json=payload, headers={"Content-Type": "application/json"})
                print("Expo response:", response.status_code, response.text)
            except Exception as e:
                print("Failed to send push:", e)

def scrape_and_update():
    response = requests.get(BASE_URL, headers=HEADERS)
    soup = BeautifulSoup(response.text, "html.parser")

    current_section = None
    count = 0
    all_tags = soup.find_all(['div', 'ul'])
    seen_keys = set()
    bulk_ops = []

    for tag in all_tags:
        if tag.name == "div":
            text = tag.get_text(strip=True)
            if text in TARGET_SECTIONS:
                current_section = text
                count = 0
                continue

        if tag.name == "ul" and current_section in TARGET_SECTIONS and count < 10:
            li = tag.find("li")
            if not li:
                continue
            h3 = li.find("h3")
            if not h3:
                continue
            a_tag = h3.find("a")
            if not a_tag:
                continue

            title = a_tag.get_text(strip=True)
            href = a_tag.get("href")
            url = urljoin(BASE_URL, href)
            sup = h3.find("sup").get_text(strip=True) if h3.find("sup") else ""
            updated_at = datetime.utcnow().isoformat()

            special = is_special_url(url)
            key = {"title": title, "section": current_section} if special else {"url": url, "section": current_section}
            unique_key = title if special else url
            seen_keys.add((current_section, unique_key))

            existing = collection.find_one(key)

            # ✅ Logic: allow insert even if sup is empty; skip update if sup is empty
            if not existing:
                should_update = True
            elif sup:
                should_update = existing.get("sup") != sup
            else:
                should_update = False

            if should_update:
                document = {
                    "title": title,
                    "url": url,
                    "sup": sup,
                    "section": current_section,
                    "order_no": str(count + 1),
                    "posted": "No",
                    "updated_at": updated_at
                }
                bulk_ops.append(UpdateOne(key, {"$set": document}, upsert=True))

            count += 1

    updated_count = 0
    if bulk_ops:
        result = collection.bulk_write(bulk_ops)
        updated_count = len(bulk_ops)

    for section in TARGET_SECTIONS:
        valid_keys = [key for sec, key in seen_keys if sec == section]
        if valid_keys:
            collection.delete_many({
                "section": section,
                "$nor": [{"url": k} if "http" in k else {"title": k} for k in valid_keys]
            })

    # ✅ Notify admins if any updates occurred
    if updated_count > 0:
        send_push_to_admins(
            "Job Alert Admin",
            f"{updated_count} post(s) were added or updated."
        )

    return {
        "status": "ok",
        "upserted_or_updated": updated_count,
        "sections": len(TARGET_SECTIONS)
    }
