FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home appuser

COPY app.py .

USER appuser

EXPOSE 8080

CMD ["waitress-serve", "--host=0.0.0.0", "--port=8080", "app:app"]
