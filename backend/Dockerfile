FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# sentence-transformers pulls in torch. PyPI's default Linux torch wheel bundles
# the CUDA runtime (~2.5GB) which this CPU-only workload never uses, so install
# the CPU build explicitly first and let the rest resolve against it.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install -r requirements.txt

# Bake the embedding model into the image (~90 MB).
#
# Otherwise the first ingest downloads it from Hugging Face at run time, which
# means `docker compose up` on a fresh clone has a network dependency *after*
# the build, and fails in an air-gapped or rate-limited environment with a
# stack trace instead of a report. Downloading it here makes the image the
# whole deliverable, and the sample-log ingest at first boot a local operation.
ENV HF_HUB_DISABLE_TELEMETRY=1
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
