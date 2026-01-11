import os
import time
import stat
import paramiko
from paramiko import SSHConfig

def progress(filename, transferred, total):
    percent = transferred / total * 100 if total else 100
    bar_len = 30
    filled = int(bar_len * transferred / total) if total else bar_len
    bar = "=" * filled + "-" * (bar_len - filled)

    print(
        f"\r{os.path.basename(filename)} "
        f"[{bar}] {percent:6.2f}% "
        f"({transferred}/{total} bytes)",
        end="",
        flush=True
    )

    if transferred >= total:
        print()

def copy_files_ssh(host, port, user, password, source, destination, move=False):

    # --- Verbindung zum Server ---
    ssh = paramiko.SSHClient()
    ssh.load_system_host_keys()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=host, port=port, username=user, password=password)
    sftp = ssh.open_sftp()

    # --- Richtung automatisch bestimmen ---
    if os.path.exists(source):
        direction = "to_remote"
    else:
        try:
            sftp.stat(source)
            direction = "to_local"
        except FileNotFoundError:
            raise FileNotFoundError(f"Source not found on local PC or server: {source}")

    # --- Upload / Download Funktionen ---
    def upload(src, dst):
        if os.path.isdir(src):
            try:
                sftp.mkdir(dst)
            except IOError:
                pass
            for item in os.listdir(src):
                upload(os.path.join(src, item), f"{dst.rstrip('/')}/{item}")
        else:
            sftp.put(src, dst, callback=lambda x, y: progress(src, x, y))
            if move:
                os.remove(src)

    def download(src, dst):
        info = sftp.stat(src)
        if stat.S_ISDIR(info.st_mode):
            os.makedirs(dst, exist_ok=True)
            for item in sftp.listdir(src):
                download(f"{src.rstrip('/')}/{item}", os.path.join(dst, item))
            if move:
                sftp.rmdir(src)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            sftp.get(src, dst, callback=lambda x, y: progress(src, x, y))
            if move:
                sftp.remove(src)

    # --- Kopieren / Verschieben ---
    start = time.time()
    if direction == "to_local":
        download(source, destination)
    else:
        upload(source, destination)
    duration = time.time() - start

    sftp.close()
    ssh.close()
    return duration
