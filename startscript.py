from flask import Flask, request
import subprocess
import sys

app = Flask(__name__)

@app.route("/start", methods=["POST"])
def start_script():
   subprocess.Popen(["python3", "/app/youtube.py"])
   return "Sync erfolgreich gestartet!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
