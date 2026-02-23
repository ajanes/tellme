FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt

COPY server /app/server
COPY polls.yml /app/polls.yml

WORKDIR /app/server

EXPOSE 5001

CMD ["python", "app.py"]
