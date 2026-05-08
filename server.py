"""
Story Sellers — Live OTP Tracker Backend
FastAPI + WebSocket + Stex API
"""

import asyncio
import httpx
import re
import time
import json
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# ── CONFIG ────────────────────────────────────────────────────────────────────
STEX_EMAIL    = "Nurulnc100@gmail.com"
STEX_PASSWORD = "Nurulnc199915"

# ── APP ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Story Sellers OTP Tracker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── STATE ─────────────────────────────────────────────────────────────────────
class State:
    token:       str   = None
    last_login:  float = 0
    active:      dict  = {}   # phone → {svc, allocated_at, seen_otps, sessions}
    otp_log:     list  = []   # last 50 OTPs received
    clients:     list  = []   # connected WebSocket clients

state = State()

http = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=3.0, read=7.0, write=3.0, pool=2.0),
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
)

# ── STEX AUTH ─────────────────────────────────────────────────────────────────
async def stex_login() -> bool:
    if state.token and (time.time() - state.last_login < 240):
        return True
    try:
        r = await http.post(
            "https://stexsms.com/mapi/v1/mauth/login",
            json={"email": STEX_EMAIL, "password": STEX_PASSWORD}
        )
        if r.status_code == 200:
            state.token      = r.cookies.get("mauthtoken")
            state.last_login = time.time()
            return True
    except:
        pass
    return False

def auth_headers():
    return {"mauthtoken": state.token}

# ── STEX API ──────────────────────────────────────────────────────────────────
async def fetch_numbers():
    """getnum/info — today's allocated numbers + SMS."""
    if not await stex_login():
        return []
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        r = await http.get(
            "https://stexsms.com/mapi/v1/mdashboard/getnum/info",
            params={"date": today},
            headers=auth_headers()
        )
        if r.status_code == 401:
            state.token = None
            state.last_login = 0
            return await fetch_numbers()
        if r.status_code == 200:
            return r.json().get("data", {}).get("numbers", [])
    except:
        pass
    return []

async def fetch_ranges(svc: str):
    """console/info — available ranges."""
    if not await stex_login():
        return []
    try:
        r = await http.get(
            "https://stexsms.com/mapi/v1/mdashboard/console/info",
            headers=auth_headers()
        )
        if r.status_code == 200:
            logs = r.json().get("data", {}).get("logs", [])
            seen = set()
            result = []
            for l in logs:
                if svc.lower() in l.get("app_name", "").lower():
                    num = l.get("number", "")
                    if num and num not in seen:
                        seen.add(num)
                        result.append(num)
            return result[:30]
    except:
        pass
    return []

async def allocate_number(rng: str):
    """Buy a number from a range."""
    if not await stex_login():
        return None
    try:
        r = await http.post(
            "https://stexsms.com/mapi/v1/mdashboard/getnum/number",
            json={"range": rng, "is_national": False},
            headers=auth_headers()
        )
        if r.status_code == 200:
            d = r.json().get("data")
            if isinstance(d, dict):
                return str(d.get("full_number", "")) or None
            return str(d) if d else None
    except:
        pass
    return None

# ── OTP EXTRACT ───────────────────────────────────────────────────────────────
def extract_otp(msg: str, svc: str) -> str:
    svc = svc.lower()
    wa  = re.search(r"\b(\d{3})[.\-\s](\d{3})\b", msg)
    if wa and svc == "whatsapp":
        return wa.group(1) + wa.group(2)
    if svc == "facebook":
        m = re.search(r"\b(\d{6})\b", msg) or re.search(r"\b(\d{5})\b", msg)
        if m: return m.group(1)
    if svc == "telegram":
        m = re.search(r"\b(\d{5})\b", msg)
        if m: return m.group(1)
    if wa: return wa.group(1) + wa.group(2)
    codes = re.findall(r"\b\d{4,8}\b", msg)
    return codes[0] if codes else msg.strip()[:20]

# ── COUNTRY ───────────────────────────────────────────────────────────────────
COUNTRIES = {
    "1":"USA 🇺🇸","7":"Russia 🇷🇺","20":"Egypt 🇪🇬","27":"South Africa 🇿🇦",
    "30":"Greece 🇬🇷","31":"Netherlands 🇳🇱","32":"Belgium 🇧🇪","33":"France 🇫🇷",
    "34":"Spain 🇪🇸","36":"Hungary 🇭🇺","39":"Italy 🇮🇹","40":"Romania 🇷🇴",
    "41":"Switzerland 🇨🇭","43":"Austria 🇦🇹","44":"UK 🇬🇧","45":"Denmark 🇩🇰",
    "46":"Sweden 🇸🇪","47":"Norway 🇳🇴","48":"Poland 🇵🇱","49":"Germany 🇩🇪",
    "51":"Peru 🇵🇪","52":"Mexico 🇲🇽","54":"Argentina 🇦🇷","55":"Brazil 🇧🇷",
    "57":"Colombia 🇨🇴","60":"Malaysia 🇲🇾","61":"Australia 🇦🇺","62":"Indonesia 🇮🇩",
    "63":"Philippines 🇵🇭","65":"Singapore 🇸🇬","66":"Thailand 🇹🇭","81":"Japan 🇯🇵",
    "82":"South Korea 🇰🇷","84":"Vietnam 🇻🇳","86":"China 🇨🇳","90":"Turkey 🇹🇷",
    "91":"India 🇮🇳","92":"Pakistan 🇵🇰","94":"Sri Lanka 🇱🇰","95":"Myanmar 🇲🇲",
    "225":"Ivory Coast 🇨🇮","233":"Ghana 🇬🇭","234":"Nigeria 🇳🇬","237":"Cameroon 🇨🇲",
    "244":"Angola 🇦🇴","249":"Sudan 🇸🇩","250":"Rwanda 🇷🇼","254":"Kenya 🇰🇪",
    "255":"Tanzania 🇹🇿","256":"Uganda 🇺🇬","880":"Bangladesh 🇧🇩","886":"Taiwan 🇹🇼",
    "960":"Maldives 🇲🇻","966":"Saudi Arabia 🇸🇦","971":"UAE 🇦🇪","974":"Qatar 🇶🇦",
    "992":"Tajikistan 🇹🇯","994":"Azerbaijan 🇦🇿","995":"Georgia 🇬🇪","998":"Uzbekistan 🇺🇿",
}

def get_country(num: str) -> str:
    s = re.sub(r"\D", "", str(num))
    for l in [4, 3, 2, 1]:
        if s[:l] in COUNTRIES:
            return COUNTRIES[s[:l]]
    return "Global 🌐"

# ── WEBSOCKET BROADCAST ───────────────────────────────────────────────────────
async def broadcast(msg: dict):
    dead = []
    for ws in state.clients:
        try:
            await ws.send_json(msg)
        except:
            dead.append(ws)
    for ws in dead:
        state.clients.remove(ws)

# ── OTP MONITOR LOOP ──────────────────────────────────────────────────────────
async def otp_monitor():
    while True:
        await asyncio.sleep(1.5)
        try:
            # Cleanup expired (10 min)
            now = time.time()
            for phone in list(state.active.keys()):
                if now - state.active[phone]["allocated_at"] > 600:
                    del state.active[phone]
                    await broadcast({"type": "expired", "phone": phone})

            if not state.active:
                continue

            all_nums = await fetch_numbers()

            for phone, info in list(state.active.items()):
                clean_p = re.sub(r"\D", "", phone)
                for item in all_nums:
                    item_num = re.sub(r"\D", "", str(item.get("number", "")))
                    if not item_num:
                        continue
                    matched = (item_num == clean_p or
                               item_num[-10:] == clean_p[-10:] or
                               item_num[-9:]  == clean_p[-9:] or
                               clean_p in item_num)
                    if not matched:
                        continue
                    msg_text = (item.get("message") or item.get("sms") or "")
                    if not msg_text or msg_text.lower() in ("none", "null", ""):
                        continue
                    otp = extract_otp(msg_text, info["svc"])
                    if otp and otp not in info["seen_otps"]:
                        info["seen_otps"].append(otp)
                        entry = {
                            "type":    "otp",
                            "phone":   phone,
                            "otp":     otp,
                            "sms":     msg_text,
                            "svc":     info["svc"],
                            "country": get_country(phone),
                            "time":    datetime.now().strftime("%H:%M:%S"),
                        }
                        state.otp_log.insert(0, entry)
                        state.otp_log = state.otp_log[:50]
                        await broadcast(entry)

            # Broadcast timer update every cycle
            await broadcast({
                "type":   "tick",
                "active": [
                    {
                        "phone":   p,
                        "svc":     v["svc"],
                        "country": get_country(p),
                        "elapsed": int(time.time() - v["allocated_at"]),
                        "otps":    len(v["seen_otps"]),
                    }
                    for p, v in state.active.items()
                ]
            })

        except Exception as e:
            print(f"[Monitor] {e}")

# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    with open("index.html") as f:
        return f.read()

@app.get("/api/ranges/{svc}")
async def get_ranges(svc: str):
    data = await fetch_ranges(svc)
    return {"ranges": data}

@app.post("/api/number")
async def get_number(body: dict):
    rng = body.get("range", "")
    svc = body.get("svc", "unknown")
    if not rng:
        raise HTTPException(400, "range required")
    num = await allocate_number(rng)
    if not num:
        raise HTTPException(503, "No number available")
    state.active[num] = {
        "svc":          svc,
        "allocated_at": time.time(),
        "seen_otps":    [],
    }
    await broadcast({
        "type":    "new_number",
        "phone":   num,
        "svc":     svc,
        "country": get_country(num),
    })
    return {"number": num, "country": get_country(num)}

@app.delete("/api/number/{phone}")
async def cancel_number(phone: str):
    if phone in state.active:
        del state.active[phone]
        await broadcast({"type": "cancelled", "phone": phone})
    return {"ok": True}

@app.get("/api/log")
async def get_log():
    return {"log": state.otp_log}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    state.clients.append(ws)
    # Send current state on connect
    await ws.send_json({
        "type": "init",
        "active": [
            {
                "phone":   p,
                "svc":     v["svc"],
                "country": get_country(p),
                "elapsed": int(time.time() - v["allocated_at"]),
                "otps":    len(v["seen_otps"]),
            }
            for p, v in state.active.items()
        ],
        "log": state.otp_log[:20],
    })
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        state.clients.remove(ws)

# ── STARTUP ───────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    await stex_login()
    asyncio.create_task(otp_monitor())
    print("🚀 Story Sellers OTP Tracker — Live!")
    # Railway / Render fix
import os
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
