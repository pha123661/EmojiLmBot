FROM python:3.8-slim-buster

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN apt-get update && \
    apt-get install --no-install-recommends --yes build-essential wget && \
    pip install --no-cache-dir -r requirements.txt && \
    python -m nltk.downloader punkt_tab && \
    wget https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz -O lid.176.ftz

COPY ./app/*.py /app

EXPOSE 8000

CMD ["python", "app.py"]
