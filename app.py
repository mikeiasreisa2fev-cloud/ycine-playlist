from flask import Flask, Response, redirect, request
import requests
import re
import base64
import json
from concurrent.futures import ThreadPoolExecutor
import os

app = Flask(__name__)

# ================= CONFIGURAÇÕES (VERSÃO 17.0) =================
# MegaFlix
MEGAFLIX_API = "https://app.megafrixapi.com/TV/1.2/"
MEGAFLIX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
    "Referer": "https://megaflix.name/",
    "X-Requested-With": "XMLHttpRequest"
}

# YouCine (REST API)
YCINE_API_BASE = "https://ycineflix.tudo30.shop/wp-json/xui-pflix/v1"
YCINE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ================= UTILITÁRIOS =================
def decode_b64(data):
    try:
        data += "=" * ((4 - len(data) % 4) % 4)
        return base64.b64decode(data).decode('utf-8')
    except:
        return data

# ================= LÓGICA MEGAFLIX =================
def fetch_megaflix_page(endpoint, page=1):
    items = []
    url = f"{MEGAFLIX_API}?page={endpoint}"
    if page > 1: url += f"&p={page}"

    try:
        response = requests.post(url, headers=MEGAFLIX_HEADERS, timeout=12)
        if response.status_code == 200:
            # Captura o bloco data-data que contém o JSON Base64
            matches = re.findall(r'data-data="([^"]+)"', response.text)
            for b64_json in matches:
                try:
                    data = json.loads(decode_b64(b64_json))
                    item_id = data.get("id")
                    name = data.get("name") or data.get("titulo")
                    thumb = data.get("background") or data.get("img")

                    if item_id and name:
                        # Link intermediário para o extrator
                        encoded_id = base64.b64encode(str(item_id).encode()).decode()
                        play_type = "m_live" if endpoint == "viewChannels" else "m_vod"
                        play_url = f"{request.host_url.rstrip('/')}/play?t={play_type}&id={encoded_id}"

                        items.append({
                            "name": name.strip(),
                            "url": play_url,
                            "logo": thumb,
                            "group": f"MegaFlix | {endpoint.replace('view', '')}"
                        })
                except: continue
    except Exception as e:
        print(f"MegaFlix Error: {e}")
    return items

def get_megaflix_catalog():
    all_content = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_megaflix_page, "viewChannels")]
        for i in range(1, 4): # 3 páginas de filmes/series
            futures.append(executor.submit(fetch_megaflix_page, "viewMovies", i))
            futures.append(executor.submit(fetch_megaflix_page, "viewSeries", i))
        for f in futures: all_content.extend(f.result())
    return all_content

# ================= LÓGICA YOUCINE =================
def fetch_ycine_category_map():
    try:
        url = f"{YCINE_API_BASE}/channels/categories"
        res = requests.get(url, headers=YCINE_HEADERS, timeout=10).json()
        return {str(cat["id"]): cat["name"] for cat in res.get("data", [])}
    except: return {}

def get_ycine_catalog():
    items = []
    try:
        cat_map = fetch_ycine_category_map()
        # Busca Canais
        list_url = f"{YCINE_API_BASE}/channels?per_page=100"
        res = requests.get(list_url, headers=YCINE_HEADERS, timeout=10).json()
        raw_items = res.get("data", {}).get("items", [])

        for item in raw_items:
            # Usando o padrão de URL direta para YouCine (Speed CDN)
            stream_url = f"https://speed.megafilmeshd9.com/midia/speed-1/{item['id']}.m3u8"
            cat_name = cat_map.get(str(item.get("category_id")), "YouCine TV")
            items.append({
                "name": item["name"],
                "url": stream_url,
                "logo": item.get("thumbnail") or item.get("logo"),
                "group": f"YouCine | {cat_name}"
            })

        # Busca Filmes Recentes
        mov_url = f"{YCINE_API_BASE}/movies?per_page=50"
        res_mov = requests.get(mov_url, headers=YCINE_HEADERS, timeout=10).json()
        for mov in res_mov.get("data", {}).get("items", []):
            stream_url = f"https://speed.megafilmeshd9.com/midia/speed-1/{mov['id']}.mp4?tipo=movie"
            items.append({
                "name": mov["name"],
                "url": stream_url,
                "logo": mov.get("thumbnail"),
                "group": "YouCine | Filmes"
            })
    except Exception as e:
        print(f"YouCine Error: {e}")
    return items

# ================= ROTAS =================
@app.route('/')
def index():
    return "<h1>M3U Server V17.0</h1><p>Sistema YouCine + MegaFlix</p><a href='/playlist.m3u'>Link M3U</a>"

@app.route('/playlist.m3u')
def playlist():
    m3u = "#EXTM3U\n"
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_mega = executor.submit(get_megaflix_catalog)
        f_ycine = executor.submit(get_ycine_catalog)
        all_items = f_mega.result() + f_ycine.result()

    for item in all_items:
        tid = item["name"].lower().replace(" ", ".")
        m3u += f'#EXTINF:-1 tvg-id="{tid}" tvg-logo="{item["logo"]}" group-title="{item["group"]}",{item["name"]}\n'
        m3u += f'{item["url"]}\n'
    return Response(m3u, mimetype='application/x-mpegurl')

@app.route('/play')
def play_redirect():
    """Resolve links dinâmicos do MegaFlix em tempo real."""
    t = request.args.get('t')
    encoded_id = request.args.get('id')
    if not encoded_id: return "Erro", 400
    item_id = base64.b64decode(encoded_id).decode()

    try:
        if t == "m_live":
            # Canais MegaFlix precisam de token
            token_url = f"https://app.megafrixapi.com/get_token_channel.php?channel={item_id}"
            payload = {"id": 0, "type": "app", "headers": MEGAFLIX_HEADERS}
            res = requests.post(token_url, json=payload, headers=MEGAFLIX_HEADERS, timeout=10).json()
            # O retorno do PHP costuma ter a URL final
            final_url = res.get("url") or res.get("stream")
            if final_url: return redirect(final_url)

        elif t == "m_vod":
            # VOD MegaFlix (Filmes/Series)
            vod_url = f"{MEGAFLIX_API}?page=viewItem&id={item_id}"
            res = requests.post(vod_url, headers=MEGAFLIX_HEADERS, timeout=10)
            # Busca getSource no HTML do item
            match = re.search(r"getSource\('([^']+)'", res.text)
            if match: return redirect(decode_b64(match.group(1)))

    except: pass
    return "Stream não encontrado", 404

if __name__ == "__main__":
    # Render configura a porta via variável de ambiente
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
