FROM python:3.13-alpine
WORKDIR /app
COPY updater.py /app/updater.py
COPY plugins.json /config/plugins.json
ENTRYPOINT ["python", "/app/updater.py"]
