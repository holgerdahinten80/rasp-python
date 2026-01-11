import os
from datetime import datetime
from PIL import Image, ExifTags
import numpy as np
from moviepy.video.VideoClip import ImageClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
from moviepy import concatenate_videoclips

# ===================== Hilfsfunktion =====================
def load_image_correct_orientation(path):
    """
    Lädt ein Bild mit korrekter EXIF-Orientierung.
    Hochkant-Bilder (Portrait) werden richtig gedreht.
    """
    img = Image.open(path)

    try:
        # EXIF-Orientierung erkennen
        for orientation in ExifTags.TAGS.keys():
            if ExifTags.TAGS[orientation] == 'Orientation':
                break

        exif = img._getexif()
        if exif is not None:
            orientation_value = exif.get(orientation, None)
            if orientation_value == 3:
                img = img.rotate(180, expand=True)
            elif orientation_value == 6:
                img = img.rotate(270, expand=True)
            elif orientation_value == 8:
                img = img.rotate(90, expand=True)
    except Exception:
        pass  # keine EXIF-Info vorhanden, einfach weiter

    return img

# ===================== Hauptfunktion =====================
def create_image_videos(image_folder, video_size=(1920, 1080), duration_per_image=3):
    """
    Erstellt Videos pro Datum aus Bildern im Ordner `image_folder`.
    - Bilder werden nach Datum im Dateinamen gruppiert (IMG_<date>_<time>_<title>.jpg)
    - Jedes Bild wird für `duration_per_image` Sekunden gezeigt
    - Bilder behalten ihre Originalgröße, schwarze Balken füllen den Rest
    - Videos werden im Ordner 'videos' gespeichert
    """
    if not os.path.exists(image_folder):
        print(f"Ordner existiert nicht: {image_folder}")
        return

    output_folder = os.path.join(image_folder, "videos")
    os.makedirs(output_folder, exist_ok=True)

    # Alle Bilddateien im Ordner
    files = [f for f in os.listdir(image_folder) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]

    # Gruppieren nach Datum (IMG_<date>_<time>_<title>.jpg)
    grouped = {}
    titles = {}
    for file in files:
        name, _ = os.path.splitext(file)
        parts = name.split('_', 3)
        if len(parts) < 3:
            continue

        date = parts[1]
        title = parts[3] if len(parts) > 3 else ""
        grouped.setdefault(date, []).append(os.path.join(image_folder, file))
        titles[os.path.join(image_folder, file)] = title

    # Videos pro Datum erstellen
    for date, images in grouped.items():
        images.sort()  # chronologisch
        clips = []
        first_title_for_video = ""

        for img_path in images:
            pil_img = load_image_correct_orientation(img_path)
            img_clip = ImageClip(np.array(pil_img))

            # Skalierungsfaktor (maximal ins Video einpassen)
            scale = min(video_size[0] / img_clip.w, video_size[1] / img_clip.h)
            img_clip = (
                img_clip
                .resized(new_size=(int(img_clip.w * scale), int(img_clip.h * scale)))
                .with_duration(duration_per_image)
                .with_position("center", "center")
            )

            # Schwarzer Hintergrund
            final_clip = CompositeVideoClip([img_clip], size=video_size, bg_color=(0,0,0))
            clips.append(final_clip)

            if not first_title_for_video:
                first_title_for_video = titles.get(img_path, "")

        # Alle Clips zusammenfügen
        if clips:
            video = concatenate_videoclips(clips, method="compose")

            # Videoname
            safe_title = first_title_for_video.replace(" ", "_").replace(".", "")
            output_filename = f"VID_{date}_{safe_title}.mp4" if safe_title else f"VID_{date}.mp4"
            output_path = os.path.join(output_folder, output_filename)

            video.write_videofile(output_path, fps=24)
            print(f"Video erstellt: {output_path}")

# ===================== Hauptprogramm =====================
def main():
    image_folder = input("Gib den Pfad zum Bilderordner ein: ").strip()
    image_folder = image_folder.strip('\'"')
    create_image_videos(image_folder)

if __name__ == "__main__":
    main()
