FROM python:3.8-slim-buster

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

COPY ./app.py /app

EXPOSE 8000

CMD ["python", "app.py"]
