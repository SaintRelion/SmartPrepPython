# Dockerfile
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /code

COPY requirements.txt /code/
WORKDIR /code

RUN pip install --no-cache-dir -r requirements.txt

COPY . /code

# Copy start.sh and make it executable
COPY entrypoint.sh /code/entrypoint.sh
RUN chmod +x /code/entrypoint.sh

# Use start.sh as the container entrypoint
ENTRYPOINT ["/code/entrypoint.sh"]