FROM python:3.11-slim

WORKDIR /app

# Cache deps layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# HuggingFace Spaces default port
EXPOSE 7860

# Writable DB path for ephemeral container
ENV DB_DIR=/tmp

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
