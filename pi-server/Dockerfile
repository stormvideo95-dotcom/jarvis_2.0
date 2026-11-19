FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 DENO_INSTALL=/usr/local
WORKDIR /app

# curl + unzip for the voice download and Deno (yt-dlp needs a JS runtime for YouTube)
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip ca-certificates \
 && curl -fsSL https://deno.land/install.sh | sh -s -- -y \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Wake words (openWakeWord, ONNX engine only) + the 4 ready-made models
RUN pip install --no-cache-dir --no-deps "openwakeword==0.6.0" \
 && pip install --no-cache-dir scipy tqdm requests \
 && python -c "from openwakeword import utils; utils.download_models(model_names=['hey_jarvis','alexa','hey_mycroft','hey_rhasspy'])"

# Flemish Piper voice (nathalie). Swap for nl_BE-rdh-medium if you want a male voice.
RUN mkdir -p /voices \
 && curl -fsSL -o /voices/nl_BE-nathalie-medium.onnx \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/nl/nl_BE/nathalie/medium/nl_BE-nathalie-medium.onnx \
 && curl -fsSL -o /voices/nl_BE-nathalie-medium.onnx.json \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/nl/nl_BE/nathalie/medium/nl_BE-nathalie-medium.onnx.json

RUN mkdir -p /data
COPY app ./app
CMD ["sh", "-c", "python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8790}"]
