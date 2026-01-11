FROM python:3.12-slim

WORKDIR /app

# Systemabhängige Pakete installieren (FFmpeg + Build-Tools)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Python-Abhängigkeiten
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App-Code kopieren (nur danach, damit Pip-Layer cached bleibt)
COPY . .

# Ports für Flask
EXPOSE 5000

# Python-Container startet den HTTP-Server
CMD ["python3", "startscript.py"]