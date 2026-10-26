import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
from collections import defaultdict, deque
from urllib.parse import quote, urlparse

import yt_dlp
from flask import Flask, Response, jsonify, request, send_from_directory
from yt_dlp.utils import DownloadError

app = Flask(__name__, static_folder="static", static_url_path="/static")

# Só aceita links desses domínios (e subdomínios, ex.: vm.tiktok.com, www.instagram.com)
ALLOWED_DOMAINS = ("instagram.com", "tiktok.com")

MAX_FILESIZE = int(os.environ.get("MAX_FILESIZE_MB", "300")) * 1024 * 1024
RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MIN", "12"))
COOKIES_FILE = os.environ.get("COOKIES_FILE")  # opcional, ajuda com Instagram
download_slots = threading.BoundedSemaphore(int(os.environ.get("MAX_PARALLEL", "3")))

_hits = defaultdict(deque)
_hits_lock = threading.Lock()


def client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or "?"


def rate_limited():
    now = time.time()
    ip = client_ip()
    with _hits_lock:
        if len(_hits) > 5000:  # limpeza simples para não crescer sem fim
            for k in [k for k, q in _hits.items() if not q or now - q[-1] > 60]:
                del _hits[k]
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            return True
        q.append(now)
    return False


def valid_url(raw):
    try:
        p = urlparse((raw or "").strip())
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    host = p.hostname.lower()
    if not any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS):
        return None
    return p.geturl()


def base_opts():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 2,
    }
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    return opts


def friendly_error(msg):
    m = msg.lower()
    if "private" in m or "login" in m or "log in" in m or "cookies" in m:
        return "Esse vídeo é privado ou exige login. Só consigo baixar vídeos públicos."
    if "unsupported url" in m:
        return "Link não suportado. Use o link de compartilhamento do vídeo (Reels, post ou TikTok)."
    if "not found" in m or "404" in m or "unavailable" in m or "removed" in m:
        return "Vídeo não encontrado. Ele pode ter sido apagado."
    if "too large" in m or "max-filesize" in m or "larger than" in m:
        return "O vídeo é grande demais para baixar por aqui."
    if "429" in m or "rate" in m:
        return "A plataforma limitou o acesso por agora. Tente de novo em alguns minutos."
    return "Não consegui processar esse link. Confira se o vídeo é público e tente novamente."


def stream_and_cleanup(path, tmp, chunk=64 * 1024):
    """Envia o arquivo e apaga a pasta temporária no fim (ou se o cliente desconectar)."""
    try:
        with open(path, "rb") as f:
            while True:
                data = f.read(chunk)
                if not data:
                    break
                yield data
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.get("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/healthz")
def healthz():
    return jsonify(ok=True)


@app.post("/api/info")
def info():
    if rate_limited():
        return jsonify(error="Muitas requisições. Aguarde um minuto."), 429

    data = request.get_json(silent=True) or {}
    url = valid_url(data.get("url"))
    if not url:
        return jsonify(error="Cole um link válido do Instagram ou do TikTok."), 400

    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            meta = ydl.extract_info(url, download=False)
    except DownloadError as e:
        return jsonify(error=friendly_error(str(e))), 422
    except Exception:
        return jsonify(error="Erro inesperado ao ler o link."), 500

    if meta.get("entries"):  # carrossel/playlist: pega o primeiro item
        entries = [e for e in meta["entries"] if e]
        if not entries:
            return jsonify(error="Nenhum vídeo encontrado nesse link."), 422
        meta = entries[0]

    heights = sorted(
        {
            f["height"]
            for f in meta.get("formats", [])
            if f.get("height") and f.get("vcodec") not in (None, "none")
        },
        reverse=True,
    )

    return jsonify(
        title=meta.get("title") or meta.get("description") or "Vídeo",
        uploader=meta.get("uploader") or meta.get("channel") or "",
        thumbnail=meta.get("thumbnail") or "",
        duration=meta.get("duration"),
        heights=heights,
    )


@app.get("/api/download")
def download():
    if rate_limited():
        return jsonify(error="Muitas requisições. Aguarde um minuto."), 429

    url = valid_url(request.args.get("url"))
    if not url:
        return jsonify(error="Link inválido."), 400

    kind = request.args.get("kind", "video")
    height = request.args.get("height", "")

    if not download_slots.acquire(blocking=False):
        return jsonify(error="Servidor ocupado. Tente novamente em instantes."), 503

    tmp = tempfile.mkdtemp(prefix="dl_")
    try:
        opts = base_opts()
        opts.update(
            {
                "outtmpl": os.path.join(tmp, "%(id)s.%(ext)s"),
                "max_filesize": MAX_FILESIZE,
            }
        )
        if kind == "audio":
            opts.update(
                {
                    "format": "bestaudio/best",
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        }
                    ],
                }
            )
            mime = "audio/mpeg"
        else:
            if height.isdigit():
                fmt = f"bv*[height<={int(height)}]+ba/b[height<={int(height)}]/b"
            else:
                fmt = "bv*+ba/b"
            opts.update({"format": fmt, "merge_output_format": "mp4"})
            mime = "video/mp4"

        with yt_dlp.YoutubeDL(opts) as ydl:
            meta = ydl.extract_info(url, download=True)
            if meta.get("entries"):
                meta = next((e for e in meta["entries"] if e), meta)

        files = [os.path.join(tmp, f) for f in os.listdir(tmp)]
        if not files:
            raise RuntimeError("arquivo não gerado")
        path = max(files, key=os.path.getsize)
    except DownloadError as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return jsonify(error=friendly_error(str(e))), 422
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        return jsonify(error="Falha ao gerar o arquivo. Tente novamente."), 500
    finally:
        download_slots.release()

    title = re.sub(r"[^\w\- ]+", "", meta.get("title") or "video", flags=re.UNICODE)
    title = title.strip()[:60] or "video"
    ext = os.path.splitext(path)[1] or (".mp3" if kind == "audio" else ".mp4")

    full_name = f"{title}{ext}"
    ascii_name = unicodedata.normalize("NFKD", full_name).encode("ascii", "ignore").decode() or f"video{ext}"
    resp = Response(stream_and_cleanup(path, tmp), mimetype=mime)
    resp.headers["Content-Length"] = str(os.path.getsize(path))
    resp.headers["Content-Disposition"] = (
        f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(full_name)}'
    )
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
