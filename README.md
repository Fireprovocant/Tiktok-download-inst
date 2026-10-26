# Baixador de vídeos Instagram e TikTok

Site simples: o usuário cola o link de compartilhamento, escolhe a qualidade e baixa o vídeo (MP4 com áudio) ou só o áudio (MP3). Para TikTok, o yt-dlp pega a versão sem marca d'água.

## Como rodar no seu computador

Pré-requisitos: Python 3.10+ e ffmpeg instalado (`sudo apt install ffmpeg` no Linux, `brew install ffmpeg` no Mac, ou baixe em ffmpeg.org no Windows).

```bash
cd baixador
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Abra http://localhost:5000

## Como colocar online

**Com Docker (VPS, Railway, Render, Fly.io):**

```bash
docker build -t baixador .
docker run -p 8000:8000 baixador
```

Em Render ou Railway, basta apontar para a pasta com o Dockerfile; a variável `PORT` é lida automaticamente.

## Configurações opcionais (variáveis de ambiente)

| Variável | Padrão | Para que serve |
|---|---|---|
| `MAX_FILESIZE_MB` | 300 | Tamanho máximo do vídeo |
| `RATE_LIMIT_PER_MIN` | 12 | Requisições por minuto por IP |
| `MAX_PARALLEL` | 3 | Downloads simultâneos |
| `COOKIES_FILE` | vazio | Caminho de um cookies.txt (ajuda quando o Instagram bloqueia) |

## Manutenção importante

- **Atualize o yt-dlp com frequência** (`pip install -U yt-dlp`). Instagram e TikTok mudam o site toda hora e o download quebra quando a versão fica velha. No Docker, reconstrua a imagem de tempos em tempos.
- O Instagram bloqueia IPs de servidores com frequência. Se der erro de login, exporte os cookies de uma conta secundária para um `cookies.txt` e use `COOKIES_FILE`.
- Só funciona com vídeos públicos.

## Aviso legal

Baixar conteúdo de terceiros pode violar os termos de uso das plataformas e direitos autorais. Se for publicar o site, deixe claro que o uso é apenas para conteúdo próprio ou autorizado, e tenha uma forma de contato para pedidos de remoção.
