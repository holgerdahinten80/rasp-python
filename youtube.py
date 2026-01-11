import os
import sys
import hashlib
import pickle
import warnings
import subprocess
import json
import re
import webbrowser
import pdb
import shutil
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from html import escape
from collections import defaultdict
from copyfilessh import copy_files_ssh
from tqdm import tqdm
from datetime import datetime
from create_image_video import create_image_videos

TOKEN_FILE = "token.pkl"
CLIENT_SECRETS_FILE = "client_secret.json"
SCOPES = ["https://www.googleapis.com/auth/youtube"]

def get_upload_playlist_id(youtube):
    response = youtube.channels().list(
        part="contentDetails",
        mine=True
    ).execute()
    return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


def get_video_duration_ffprobe(file_path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration",
            "-of", "json",
            file_path
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def seconds_to_iso8601(seconds):
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    iso = "PT"
    if h:
        iso += f"{h}H"
    if m:
        iso += f"{m}M"
    if s or iso == "PT":
        iso += f"{s}S"
    return iso


def get_all_videos(youtube, upload_playlist_id):
    videos = []
    next_page_token = None

    # 1. Alle Videos aus der Playlist holen
    while True:
        response = youtube.playlistItems().list(
            part="snippet",
            playlistId=upload_playlist_id,
            maxResults=50,
            pageToken=next_page_token
        ).execute()

        for item in response["items"]:
            videos.append({
                "videoId": item["snippet"]["resourceId"]["videoId"],
                "title": item["snippet"]["title"],
                "duration": None  # Platzhalter
            })

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    # 2. Durations batchweise abrufen (max. 50 IDs)
    for i in range(0, len(videos), 50):
        batch = videos[i:i + 50]
        video_ids = ",".join(v["videoId"] for v in batch)

        response = youtube.videos().list(
            part="contentDetails",
            id=video_ids
        ).execute()

        duration_map = {
            item["id"]: item["contentDetails"]["duration"]
            for item in response["items"]
        }

        # 3. Duration zuordnen
        for video in batch:
            video["duration"] = duration_map.get(video["videoId"])        

    return videos

def get_youtube_videos(youtube):
   
    if not youtube:
        youtube = get_youtube_service()

    playlist_id = get_upload_playlist_id(youtube)
    videos = get_all_videos(youtube, playlist_id)

    return videos

def get_youtube_service():
    creds = None

    # 1️⃣ Prüfen, ob Token existiert
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    # 2️⃣ Token erneuern, falls abgelaufen
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    # 3️⃣ Kein gültiger Token -> einmaliger OAuth-Flow (nur lokal)
    if not creds:
        flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)   
        # Lokaler Server öffnet automatisch den Browser
        creds = flow.run_local_server(port=0)

        # Token speichern
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
            
    # 4️⃣ Service bauen
    return build("youtube", "v3", credentials=creds)


# Video hochladen
def upload_video(youtube, file_path, title=None, description=""):
    if title is None:
        title = os.path.splitext(os.path.basename(file_path))[0]

    # --- Media mit echter Chunk-Größe (wichtig für Progress!) ---
    media = MediaFileUpload(
        file_path,
        chunksize= 1024 * 1024,  # 1 MB
        resumable=True
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description
            },
            "status": {
                "privacyStatus": "unlisted",
                "madeForKids": False
            }
        },
        media_body=media
    )

    # --- Upload mit Progress ---
    response = None

    file_size = os.path.getsize(file_path)
    with tqdm(total=file_size, unit="B", unit_scale=True, desc=f"Upload {title}") as pbar:
        while response is None:
            status, response = request.next_chunk()
            if status:
                pbar.update(int(status.resumable_progress - pbar.n))
        # --- sicherstellen, dass Balken 100% ist ---
        if pbar.n < file_size:
            pbar.update(file_size - pbar.n)

    print(f"✅ Video hochgeladen: {title}")

    # --- Duration aus Datei ermitteln ---
    duration_seconds = get_video_duration_ffprobe(file_path)
    duration_iso = seconds_to_iso8601(duration_seconds)

    # --- Cache-Eintrag ---
    video_entry = {
        "videoId": response["id"],
        "title": title,
        "duration": duration_iso
    }

    return video_entry

def upload_all_videos(root_directory):

    uploaded_video_count = 0
    youtube = get_youtube_service()

    videos = get_youtube_videos(youtube)

    uploaded_titles = [v["title"] for v in videos]

    extensions = [".mts", ".mts2", ".m2ts", ".avi", ".vob", ".mp4", ".mpg"]

    for root, dirs, files in os.walk(root_directory):
        for file in files:
            if any(file.lower().endswith(ext) for ext in extensions):
                path = os.path.join(root, file)
            
                if not os.path.isfile(path):
                    continue

                if file in uploaded_titles or file.replace("_", " ") in uploaded_titles:
                    print(f"{file} wurde bereits hochgeladen überspringen")
                else:
                    v = upload_video(youtube, path)
                    videos.append(v)
                    uploaded_video_count += 1

    print(f"{uploaded_video_count} Videos auf YouTube hochgeladen")

    videos_sorted = sorted(videos, key=lambda v: v["title"].lower())
    return videos_sorted   

def get_sorted_videos(youtube=None):

    videos = get_youtube_videos(youtube)
    print(f"{len(videos)} Videos gefunden")

    videos_sorted = sorted(videos, key=lambda v: v["title"].lower())
    return videos_sorted

def generate_html(videos):
    import re
    from html import escape
    from collections import defaultdict

    # ---------- Hilfsfunktion: ISO-8601 → hh:mm:ss ----------
    def iso_to_hms(duration):
        if not duration:
            return "00:00"
        m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
        if not m:
            return duration
        h = int(m.group(1) or 0)
        m_ = int(m.group(2) or 0)
        s = int(m.group(3) or 0)
        return f"{h}:{m_:02}:{s:02}" if h else f"{m_}:{s:02}"

    # --- 1️⃣ Metadaten extrahieren ---
    for v in videos:
        raw = v.get("title", "")
        
        # Datum aus Titel
        m_date = re.search(r'(\d{8})', raw)
        v["_date"] = m_date.group(1) if m_date else "00000000"
        if v["_date"] != "00000000":
            v["_display_date"] = f"{v['_date'][6:8]}.{v['_date'][4:6]}.{v['_date'][0:4]}"
            v["_year"] = v["_date"][:4]
        else:
            v["_display_date"] = "Unbekannt"
            v["_year"] = "Unbekannt"

        # Extratitel
        m_title = re.match(r'VID[_ ]\d{8}(?:[_ ]\d{6})?\s*(.*)', raw)
        title = m_title.group(1).strip() if m_title and m_title.group(1).strip() else ""
        v["_extra_title"] = re.sub(r"[_-]", " ", title).strip()

        # Dauer
        v["_duration"] = iso_to_hms(v.get("duration", ""))
        v["_is_long"] = v["_duration"].count(":") == 2

        # Slideshow = kein Zeit-Token (6 Ziffern) direkt nach Datum
        v["_is_slideshow"] = not bool(re.search(r'\d{8}[_ ]\d{6}', raw))

    # --- 2️⃣ Sortieren & Gruppieren ---
    videos_sorted = sorted(videos, key=lambda x: x["_date"], reverse=True)
    by_date = defaultdict(list)
    years, titles = set(), set()
    title_years = defaultdict(set)

    for v in videos_sorted:
        by_date[v["_date"]].append(v)
        if v["_year"] != "Unbekannt":
            years.add(v["_year"])
        if v["_extra_title"]:
            titles.add(v["_extra_title"])
            title_years[v["_extra_title"]].add(v["_year"])

    sorted_dates = sorted(by_date.keys(), reverse=True)
    sorted_years = sorted(years, reverse=True)
    
    sorted_titles = sorted(
        [(y, t) for t, ys in title_years.items() for y in ys],
        key=lambda x: (-int(x[0]), x[1])
    )

    # Erstes Datum pro Titel
    title_first_date = {}
    for d in sorted_dates:
        for v in by_date[d]:
            t = v["_extra_title"]
            if t and t not in title_first_date:
                title_first_date[t] = d

    # Erstes Datum pro Jahr
    year_first_date = {}
    for d in sorted_dates:
        for v in by_date[d]:
            y = v["_year"]
            if y not in year_first_date:
                year_first_date[y] = d

    # --- 3️⃣ HTML ---
    html = [
        "<!DOCTYPE html><html lang='de'><head><meta charset='UTF-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        "<title>YouTube Videos</title>",
        "<style>",
        "body{font-family:Arial;background:#111;color:#eee;margin:0;padding:0}",
        "#current-date{position:fixed;bottom:0;right:0;background:#222;color:#4ea1ff;font-size:24px;padding:10px 0;z-index:999}",
        "#yearFilter{width:7ch;}",
        ".filters{position:fixed;top:0;left:0;display:flex;gap:20px;justify-content:flex-start;padding:10px;z-index:998}",
        "select{padding:5px;font-size:16px}",
        ".container{display:flex;flex-direction:column;align-items:center;margin-top:10px}",
        ".videos-row{display:flex;flex-wrap:wrap;justify-content:center;gap:20px;margin-bottom:25px}",
        ".video-container{display:flex;flex-direction:column;align-items:center}",
        ".video{width:320px;display:flex;flex-direction:column;align-items:center}",
        ".thumb{position:relative;cursor:pointer;height:180px;width:100%}",
        ".thumb iframe { width: 100%; height: 100%; }",
        ".thumb img{width:100%;height:100%;border-radius:10px;object-fit:cover}",
        ".play{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:40px;color:white}",
        ".duration-overlay{position:absolute;bottom:6px;right:6px;background:rgba(0,0,0,0.75);color:#fff;font-family:monospace;font-size:12px;padding:3px 7px;border-radius:4px;pointer-events:none;transition:opacity .2s;line-height:1.2em;text-align:center}",
        ".duration-overlay.long{font-size:14px;font-weight:bold}",
        ".duration-overlay.slideshow{background:rgba(255,165,0,0.85);font-weight:bold}",  # Slideshow Hinweis
        ".video-id{font-size:12px;color:#777;font-family:monospace;margin-top:2px}",
        ".date{text-align:center;color:#aaa;font-size:14px;margin-top:2px}",
        ".group-title{display: block; width: 100%; font-size: 34px; font-weight: bold; text-align: center; margin: 40px 0 15px;}",

        "/* 📱 Mobile: 2 Videos pro Zeile */",
        "@media (max-width: 768px) {",
        "   html, body { width: 100%; margin: 0; padding: 0; overflow-x: hidden; }",
        "   body { padding-left: env(safe-area-inset-left); padding-right: env(safe-area-inset-right); }",
        "   .container { width: 100%; max-width: 100%; padding: 0; margin: 0; }",
        "   .videos-row { display: block; width: 100%; padding: 0; margin: 0; }",
        "   .video { width: 100%; max-width: 100%; margin: 0 0 12px 0; padding: 0; box-sizing: border-box; display: flex; flex-direction: column; align-items: center; }",
        "   .thumb { width: 100%; height: 56vw; max-height: 360px; margin: 0; position: relative; overflow: hidden; }",
        "   .thumb img { width: 100%; height: 100%; display: block; object-fit: cover; border-radius: 10px; }",
        "   .thumb iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: none; display: block; }",
        "   .duration-overlay { position: absolute; bottom: 6px; right: 6px; background: rgba(0,0,0,0.75); color: #fff; font-family: monospace; font-size: 12px; padding: 3px 7px; border-radius: 4px; pointer-events: none; line-height: 1.2em; text-align: center; }",
        "   .video-id, .date { text-align: center; margin: 2px 0 0 0; font-size: 12px; color: #ccc; line-height: 1em; position: relative; z-index: 1; }",
        "   .video-id-date { display: flex; justify-content: center; gap: 6px; }",
        "   .play { font-size: 32px; }",
        "   .group-title { font-size: 26px; margin: 30px 0 12px; text-align: center; }",
        "   select { width: 100%; font-size: 18px; }",
        "   #current-date { font-size: 18px; padding: 8px 0; text-align: center; }",        
        "}",

        "</style>",
        "<script>",
        "function loadVideo(c,id){",
        "  c.innerHTML=`<iframe src='https://www.youtube.com/embed/${id}?autoplay=1' allow='autoplay; fullscreen' allowfullscreen></iframe>`;",
        "}",
        "function gotoYear(){",
        "  const year=document.getElementById('yearFilter').value;",
        "  // Scrollen zum ersten Video des gewählten Jahres",
        "  if(year){",
        "    const firstVideo=Array.from(document.querySelectorAll('.video-container')).find(v=>v.dataset.year===year);",
        "    if(firstVideo){",
        "      const row = firstVideo.closest('.videos-row');",
        "      if(row){",
        "        row.scrollIntoView({ behavior:'smooth', block:'start' });",
        "      }",
        "    }",
        "  }",
        "}",
        "function gotoTitle(){",
        "  const title=document.getElementById('titleFilter').value;",
        "  // Scrollen zum ersten Video mit dem gewählten Titel",
        "  if(title){",
        "    const target=Array.from(document.querySelectorAll('.group-title')).find(t=>t.dataset.title===title);",
        "    if(target) target.scrollIntoView({behavior:'smooth', block:'start'});",
        "  }",
        "}",        
        "// Sticky-Datum",
        "window.addEventListener('scroll', () => {",
        "const months=['Januar','Februar','März','April','Mai','Juni','Juli','August','September','Oktober','November','Dezember'];",
        "const sticky=document.getElementById('current-date');",
        "let lastVisible=null;",
        "document.querySelectorAll('.video-container').forEach(v=>{",
        "  const rect=v.getBoundingClientRect();",
        "  if(rect.top<=60){ lastVisible=v; }",
        "});",
        "if(lastVisible){",
        "  const parts=lastVisible.querySelector('.date').textContent.split('.');",
        "  if(parts.length===3){",
        "    const day=parts[0], month=months[parseInt(parts[1],10)-1], year=parts[2];",
        "    sticky.textContent=`${day}. ${month} ${year}`;",
        "  } else {",
        "    sticky.textContent=lastVisible.querySelector('.date').textContent;",
        "  }",
        "} else {",
        "  sticky.textContent='Datum';",
        "}",
        "});",
        "</script></head><body>",
        "<div id='current-date'>Datum</div>",
        "<div class='filters'>",
        "<label>Jahr: <select id='yearFilter' onchange='gotoYear()'><option value=''>Alle</option>",
        *[f"<option value='{y}'>{y}</option>" for y in sorted_years],
        "</select></label>",
        "<label>Titel: <select id='titleFilter' onchange='gotoTitle()'><option value=''>Alle</option>",
        *[f"<option value='{escape(t)}'>{y} {escape(t)}</option>" for y, t in sorted_titles],
        "</select></label>",
        "</div>",
        "<div class='container'>"
    ]

    printed_titles = set()
    for d in sorted_dates:
        vids = by_date[d]

        html.append("<div class='videos-row'>")

        for v in vids:
            t = v["_extra_title"]
            key = (v["_year"], t)

            # 🔹 Titel DIREKT vor dem ersten passenden Video ausgeben
            if t and key not in printed_titles:
                years_for_title = ",".join(sorted(title_years[t]))
                html.append(
                    f"<div class='group-title' data-title='{t}' data-year='{v['_year']}' data-years='{years_for_title}'>"
                    f"{escape(t)}</div>"
                )
                printed_titles.add(key)

            vid = v.get("videoId") or v.get("video_id")

            # Dauer in Sekunden
            dur_parts = v["_duration"].split(":")
            if len(dur_parts) == 3:
                seconds = int(dur_parts[0])*3600 + int(dur_parts[1])*60 + int(dur_parts[2])
            elif len(dur_parts) == 2:
                seconds = int(dur_parts[0])*60 + int(dur_parts[1])
            else:
                seconds = 0

            thumb = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"

            # Kurze Videos: kein Play, keine Overlay
            if seconds <= 3:
                overlay_html = ""
                play_html = ""
            else:
                # Overlay-Text
                overlay_lines = []
                if v["_is_slideshow"]:
                    overlay_lines.append("Slideshow")
                overlay_lines.append(v["_duration"])
                overlay_text = "<br>".join(overlay_lines)

                overlay_class = "duration-overlay long" if v["_is_long"] else "duration-overlay"
                if v["_is_slideshow"]:
                    overlay_class += " slideshow"

                overlay_html = f"<div class='{overlay_class}'>{overlay_text}</div>"
                play_html = "<div class='play'>▶</div>"                   

            html.extend([
                f"<div class='video-container' data-year='{v['_year']}' data-title='{t}'>",
                "  <div class='video'>",
                f"    <div class='thumb' onclick=\"loadVideo(this,'{vid}')\">",
                f"      <img src='{thumb}'>",
                f"      {overlay_html}",
                f"      {play_html}",
                "       <div class='play'>▶</div>" if seconds > 3 else "",
                "    </div>",
                "    <div class='video-id-date'>",
                f"      <div class='video-id'>ID: {vid}</div>",
                f"      <div class='date'>{v['_display_date']}</div>",
                "    </div>",
                "  </div>",
                "</div>"
            ])

        html.append("</div>")

    html.append("</div></body></html>")
    return "\n".join(html)

def create_youtube_html(videos_sorted = None):
    if videos_sorted == None:
        videos_sorted = get_sorted_videos()

    html_content = generate_html(videos_sorted)

    OUTPUT_HTML = "/html/index.html"
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_content)    


def copy_handy_media():

    HOST = "192.168.178.178"
    USER = "u0_a371"
    PORT = 8022
    PWD = os.environ.get("SSH_PASSWORD")

    SOURCE = "/data/data/com.termux/files/home/sdcard/dcim/Camera"

    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    DEST = os.path.abspath(f"/handy/{today}")
    os.makedirs(DEST, exist_ok=True)

    try:
        print(f"Kopiere von {SOURCE} auf {HOST} nach {DEST}")
        duration = copy_files_ssh(host=HOST, port=PORT, user=USER, password=PWD, source=SOURCE, destination=DEST, move=True)
        print(f"\nFertig in {duration:.1f} Sekunden")
    except Exception as e:
        print("Fehler beim Kopieren:", e)

    return DEST

def start_youtube_job():
    path = copy_handy_media()
    create_image_videos(path)
    try:
        videos = upload_all_videos(path)
        shutil.rmtree(path)
        create_youtube_html(videos)
    except Exception as e:
        print("Fehler beim upload: ", e)

if __name__ == "__main__":
    start_youtube_job()
