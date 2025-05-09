# Builder stage: install dependencies and download resources
FROM python:3.10-slim AS builder
WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN apt-get update && \
    apt-get install --no-install-recommends --yes build-essential wget && \
    pip install --no-cache-dir -r requirements.txt && \
    wget https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz -O lid.176.ftz && \
    rm -rf /var/lib/apt/lists/*

# Final stage: copy only what is needed
FROM python:3.10-slim
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /app/lid.176.ftz /app/lid.176.ftz
COPY --from=builder /app/requirements.txt /app/requirements.txt

RUN python -m nltk.downloader punkt_tab

COPY ./app/*.py /app

ENTRYPOINT ["python", "app.py"]