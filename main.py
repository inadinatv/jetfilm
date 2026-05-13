#!/usr/bin/env python3
import re, json, os, time, requests, cloudscraper
from concurrent.futures import ThreadPoolExecutor, as_completed

# Cloudscraper objesini oluşturuyoruz (Gerçek bir Chrome tarayıcı taklidi yapar)
scraper = cloudscraper.create_scraper(browser={
    'browser': 'chrome',
    'platform': 'windows',
    'desktop': True
})

# ═══════════ AYARLAR ═══════════
SITE = "https://jetfilmizle.net"
MAX_PAGES = 10            # GitHub Actions süre sınırına takılmamak için sayfa sayısını optimize ettik
BATCH_SIZE = 8            # Eşzamanlı işlem sayısı

KATEGORILER = [
    {"slug": "aksiyon",          "name": "Aksiyon"},
    {"slug": "komedi",           "name": "Komedi"},
    {"slug": "dram",             "name": "Dram"},
    {"slug": "korku",            "name": "Korku"},
    {"slug": "gerilim",          "name": "Gerilim"},
    {"slug": "macera",           "name": "Macera"},
    {"slug": "animasyon",        "name": "Animasyon"},
    {"slug": "bilim-kurgu",      "name": "Bilim Kurgu"},
    {"slug": "anime",            "name": "Anime"},
    {"slug": "belgesel",         "name": "Belgesel"}
]

# ═══════════ HTML / PARSER ═══════════
def fetch_html(url, referer=None):
    try:
        headers = {"Referer": referer or SITE + "/"}
        r = scraper.get(url, headers=headers, timeout=15)
        if r.status_code != 200: 
            return None
        return r.text
    except Exception as e:
        print(f"Bağlantı hatası ({url}): {e}")
        return None

def kat_page_url(slug, page):
    return f"{SITE}/tur/{slug}" if page <= 1 else f"{SITE}/tur/{slug}/sayfa-{page}"

def parse_page(html):
    """Sayfadaki filmleri döndür: [{slug, title, poster}]"""
    films = []
    if not html: return films
    
    # JSON-LD taraması
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>', html, re.I):
        try:
            data = json.loads(m.group(1))
            if data.get("@type") == "ItemList" and "itemListElement" in data:
                for item in data["itemListElement"]:
                    mov = item.get("item")
                    if not mov or not mov.get("url"): continue
                    sm = re.search(r'/film/([^/?#]+)', mov["url"])
                    if not sm: continue
                    slug = sm.group(1)
                    title = re.sub(r'<[^>]+>', '', mov.get("name", "")).strip() or slug.replace("-", " ").title()
                    poster = mov.get("image", "")
                    films.append({"slug": slug, "title": title, "poster": poster})
                if films: break
        except: pass
    
    return films

# ═══════════ STREAM ÇÖZÜMLEME ═══════════
def extract_stream(html):
    patterns = [
        r'["\'`](?:file|url|source|src)["\'`]?\s*:\s*["\'`](https?://[^"\'`\s]+\.m3u8[^"\'`\s]*)["\'`]',
        r'["\'`](?:file|url|source|src)["\'`]?\s*:\s*["\'`](https?://[^"\'`\s]+\.mp4[^"\'`\s]*)["\'`]'
    ]
    for p in patterns:
        m = re.search(p, html, re.I)
        if m: return m.group(1).strip()
    return None

def resolve_film(slug):
    """Tek bir filmin oynatma linkini döndürür"""
    url = f"{SITE}/film/{slug}"
    html = fetch_html(url, f"{SITE}/filmler")
    if not html: return None
    
    direct = extract_stream(html)
    if direct: return direct
    
    iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.I)
    for src in iframes:
        if src.startswith("http") and "youtube" not in src:
            emb_html = fetch_html(src, url)
            if emb_html:
                return extract_stream(emb_html) or src
    return None

# ═══════════ ANA İŞLEM ═══════════
def fetch_all_category_films(kat):
    """Bir kategorideki sayfaları gezip film listesini döndürür."""
    films = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        url = kat_page_url(kat["slug"], page)
        html = fetch_html(url)
        if not html: break
        
        page_films = parse_page(html)
        if not page_films: break # Boş sayfa, kategori bitti
        
        for f in page_films:
            if f["slug"] not in seen:
                seen.add(f["slug"])
                f["group"] = kat["name"]
                films.append(f)
    return films

def main():
    # Playlists klasörünü oluştur
    os.makedirs("playlists", exist_ok=True)
    
    for kat in KATEGORILER:
        print(f"\n[{kat['name']}] kategorisi taranıyor...")
        films = fetch_all_category_films(kat)
        print(f"[{kat['name']}] {len(films)} film bulundu. Linkler çözülüyor...")
        
        m3u = ["#EXTM3U"]
        
        # Stream linklerini paralel çöz
        with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            future_to_film = {executor.submit(resolve_film, f["slug"]): f for f in films}
            for future in as_completed(future_to_film):
                f = future_to_film[future]
                try:
                    stream = future.result()
                    if stream:
                        title = f["title"].replace(",", "‚")
                        logo = f["poster"] if f["poster"] else ""
                        m3u.append(f'#EXTINF:-1 tvg-id="{f["slug"]}" tvg-name="{title}" tvg-logo="{logo}" group-title="{kat["name"]}",{title}')
                        m3u.append(stream)
                except Exception as e: 
                    pass
                
        # Eğer link bulunduysa M3U dosyasını kaydet
        if len(m3u) > 1:
            file_path = f"playlists/{kat['slug']}.m3u"
            with open(file_path, "w", encoding="utf-8") as file:
                file.write("\n".join(m3u) + "\n")
            print(f"✅ {file_path} oluşturuldu. ({len(m3u)//2} film eklendi)")
        else:
            print(f"❌ [{kat['name']}] için stream linki bulunamadı veya site engelledi.")

if __name__ == "__main__":
    start = time.time()
    main()
    print(f"\nİşlem {time.time()-start:.1f} saniye sürdü.")
