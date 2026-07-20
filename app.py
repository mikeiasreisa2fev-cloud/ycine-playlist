from flask import Flask, Response, redirect, request
import requests
import re
import base64
import json
from concurrent.futures import ThreadPoolExecutor
import os
import time

app = Flask(__name__)

# ================= CONFIGURAÇÕES (VERSÃO 21.0) =================
# MegaFlix
MEGAFLIX_API = "https://app.megafrixapi.com/TV/1.2/"
MEGAFLIX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
    "Referer": "https://megaflix.name/",
    "X-Requested-With": "XMLHttpRequest"
}

# YouCine
YCINE_API_BASE = "https://ycineflix.tudo30.shop/wp-json/xui-pflix/v1"
YCINE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Cache Simples (10 minutos)
cache = {"data": None, "time": 0}

# ================= UTILITÁRIOS =================
def decode_b64(data):
    try:
        data += "=" * ((4 - len(data) % 4) % 4)
        return base64.b64decode(data).decode('utf-8')
    except: return data

# ================= LÓGICA MEGAFLIX =================
def get_megaflix_channels():
    items = []
    try:
        response = requests.post(f"{MEGAFLIX_API}?page=viewChannels", headers=MEGAFLIX_HEADERS, timeout=20)
        if response.status_code == 200:
            matches = re.findall(r'data-data="([^"]+)"', response.text)
            for b64_json in matches:
                try:
                    data = json.loads(decode_b64(b64_json))
                    cid = data.get("id")
                    name = data.get("name") or data.get("titulo")
                    img = data.get("background") or data.get("img")

                    if cid and name:
                        encoded_id = base64.b64encode(str(cid).encode()).decode()
                        play_url = f"{request.host_url.rstrip('/')}/play?t=m&id={encoded_id}"
                        items.append({
                            "name": f"[MF] {name.strip()}",
                            "url": play_url,
                            "logo": img,
                            "group": "MEGAFLIX TV"
                        })
                except: continue
    except Exception as e:
        print(f"Erro MegaFlix: {e}")
    return items

# ================= LÓGICA YOUCINE =================
def get_ycine_channels():
    all_items = []
    try:
        cat_res = requests.get(f"{YCINE_API_BASE}/channels/categories", headers=YCINE_HEADERS, timeout=10).json()
        cat_map = {str(c["id"]): c["name"] for c in cat_res.get("data", [])}

        def fetch_page(p):
            try:
                url = f"{YCINE_API_BASE}/channels?per_page=100&page={p}"
                res = requests.get(url, headers=YCINE_HEADERS, timeout=15).json()
                return res.get("data", {}).get("items", [])
            except: return []

        with ThreadPoolExecutor(max_workers=10) as executor:
            pages = executor.map(fetch_page, range(1, 11))
            for items in pages:
                for item in items:
                    stream = f"https://speed.megafilmeshd9.com/midia/speed-1/{item['id']}.m3u8"
                    group = cat_map.get(str(item.get("category_id")), "YOUCINE TV")
                    all_items.append({
                        "name": item["name"],
                        "url": stream,
                        "logo": item.get("thumbnail") or item.get("stream_icon"),
                        "group": f"YOUCINE | {group.upper()}"
                    })
    except Exception as e:
        print(f"Erro YouCine: {e}")
    return all_items

# ================= ROTAS =================
@app.route('/')
def index():
    return "<h1>M3U Server V21.0</h1><p>MegaFlix + YouCine</p><a href='/playlist.m3u'>Playlist</a>"

@app.route('/playlist.m3u')
def playlist():
    global cache
    now = time.time()
    if cache["data"] and (now - cache["time"] < 600):
        return Response(cache["data"], mimetype='application/x-mpegurl')

    m3u = "#EXTM3U\n"
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_mega = executor.submit(get_megaflix_channels)
        f_ycine = executor.submit(get_ycine_channels)
        all_items = f_mega.result() + f_ycine.result()

    if not all_items:
        return "#EXTM3U\n# Erro ao carregar canais"

    for item in all_items:
        tid = item["name"].lower().replace(" ", ".")
        m3u += f'#EXTINF:-1 tvg-id="{tid}" tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n'
        m3u += f'{item["url"]}\n'

    cache["data"] = m3u
    cache["time"] = now
    return Response(m3u, mimetype='application/x-mpegurl')

@app.route('/play')
def play_redirect():
    t = request.args.get('t')
    eid = request.args.get('id')
    if not eid: return "Error", 400
    cid = base64.b64decode(eid).decode()
    try:
        token_url = f"https://app.megafrixapi.com/get_token_channel.php?channel={cid}"
        res = requests.post(token_url, json={"id": 0, "type": "app", "headers": MEGAFLIX_HEADERS}, headers=MEGAFLIX_HEADERS, timeout=10).json()
        final = res.get("url") or res.get("stream")
        if final: return redirect(final)
    except: pass
    return "Offline", 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
