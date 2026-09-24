FROM python:3.11-slim

# Install ffmpeg (required for voice streaming)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

# Fail the image build if the YouTube JavaScript runtime/EJS stack is not
# actually installed. yt-dlp uses Deno by default for YouTube challenge
# solving, while yt-dlp-ejs is installed by the fork's default extra.
RUN deno --version && \
    python -c "import importlib.metadata as m; import yt_dlp; print('yt-dlp:', yt_dlp.version.__version__); print('yt-dlp-ejs:', m.version('yt-dlp-ejs'))"

CMD ["python", "main.py"]
