#!/usr/bin/env python3
import re, json, os, time, requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ═══════════ AYARLAR ═══════════
SITE = "https://jetfilmizle.net"
MAX_PAGES = 30            # GitHub Actions süresini aşmamak için ideal (Artırılabilir)
BATCH_SIZE = 5             # GitHub ban riskine karşı düşük tutuldu
OUTPUT_DIR = "lists"      # M3U dosyalarının kaydedileceği klasör

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

KATEGORILER = [
    {"slug": "aksiyon", "name": "Aksiyon"},
    {"slug": "komedi", "name": "Komedi"},
    {"slug": "dram", "name": "Dram"},
    {"slug": "korku", "name": "Korku"},
    {"slug": "gerilim", "name": "Gerilim"},
    {"slug": "macera", "name": "Macera"},
    {"slug": "animasyon", "name": "Animasyon"},
    {"slug": "romantik", "name": "Romantik"},
    {"slug": "bilim-kurgu", "name": "Bilim Kurgu"},
    {"slug": "fantastik", "name": "Fantastik"},
    {"slug": "gizem", "name": "Gizem"},
    {"slug": "suc", "name": "Suç"},
    {"slug": "belgesel", "name": "Belgesel"},
    {"slug": "anime", "name": "Anime"},
    {"slug": "western", "name": "Western"},
    {"slug": "aile", "name": "Aile"}
]

# ═══════════ YARDIMCI FONKSİYONLAR ═══════════
def fetch_html(url, referer=None):
    try:
        r = requests.get(url, headers={**HEADERS, "Referer": referer or SITE + "/"}, timeout=15)
        return r.text if r.status_code == 200 else None
    except: return None

def parse_page(html):
    films = []
    if not html: return films
    # JSON-LD tarama
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>', html, re.I):
        try:
            data = json.loads(m.group(1))
            if data.get("@type") == "ItemList" and "itemListElement" in data:
                for item in data["itemListElement"]:
                    mov = item.get("item")
                    if not mov or not mov.get("url"): continue
                    slug = re.search(r'/film/([^/?#]+)', mov["url"]).group(1)
                    title = mov.get("name", "").strip()
                    poster = mov.get("image", "")
                    films.append({"slug": slug, "title": title, "poster": poster})
        except: pass
    return films

def resolve_film(slug):
    url = f"{SITE}/film/{slug}"
    html = fetch_html(url)
    if not html: return None
    # Pixeldrain kontrolü
    pd = re.search(r'pixeldrain\.com/u/([a-zA-Z0-9]+)', html)
    if pd: return f"https://pixeldrain.com/api/file/{pd.group(1)}"
    # M3U8/MP4 direkt link tarama
    stream = re.search(r'["\'`](https?://[^"\'`\s]+\.(?:m3u8|mp4)[^"\'`\s]*)["\'`]', html, re.I)
    return stream.group(1) if stream else None

# ═══════════ ANA SÜREÇ ═══════════
def process_category(kat):
    all_kat_films = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        url = f"{SITE}/tur/{kat['slug']}" if page == 1 else f"{SITE}/tur/{kat['slug']}/sayfa-{page}"
        html = fetch_html(url)
        page_films = parse_page(html)
        if not page_films: break
        
        for f in page_films:
            if f["slug"] not in seen:
                seen.add(f["slug"])
                f["group"] = kat["name"]
                all_kat_films.append(f)
    return all_kat_films

def main():
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
    
    print("Kategoriler taranıyor...")
    total_found_films = []
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(process_category, k): k for k in KATEGORILER}
        for future in as_completed(futures):
            total_found_films.extend(future.result())

    # Tekilleştirme
    unique_films = {f['slug']: f for f in total_found_films}.values()
    print(f"Toplam {len(unique_films)} film bulundu. Linkler çözülüyor...")

    # Link çözümleme
    stream_map = {}
    with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
        futures = {executor.submit(resolve_film, f['slug']): f['slug'] for f in unique_films}
        for future in as_completed(futures):
            res = future.result()
            if res: stream_map[futures[future]] = res

    # Dosyaları Oluşturma (Kategori Bazlı)
    main_m3u = ["#EXTM3U"]
    
    for kat in KATEGORILER:
        kat_m3u = ["#EXTM3U"]
        for f in unique_films:
            if f["group"] == kat["name"] and f["slug"] in stream_map:
                line = f'#EXTINF:-1 tvg-logo="{f["poster"]}" group-title="{f["group"]}",{f["title"]}\n{stream_map[f["slug"]]}'
                kat_m3u.append(line)
                main_m3u.append(line)
        
        with open(f"{OUTPUT_DIR}/{kat['slug']}.m3u", "w", encoding="utf-8") as f:
            f.write("\n".join(kat_m3u))
    
    # Ana Liste
    with open(f"{OUTPUT_DIR}/all_films.m3u", "w", encoding="utf-8") as f:
        f.write("\n".join(main_m3u))

    print("İşlem başarıyla tamamlandı.")

if __name__ == "__main__":
    main()
