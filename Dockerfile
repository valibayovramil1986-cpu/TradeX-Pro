FROM python:3.12-slim

# Sistem paketləri
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Əvvəlcə requirements (cache üçün)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kod (.dockerignore .env, .git, venv və s. istisna edir)
COPY . .

# Root olmayan istifadəçi
RUN useradd --create-home --shell /usr/sbin/nologin tradex \
    && mkdir -p logs database \
    && chown -R tradex:tradex /app
USER tradex

# Sağlamlıq yoxlaması — real DB bağlantısını yoxlayır
HEALTHCHECK --interval=60s --timeout=15s --start-period=90s --retries=3 \
    CMD python -c "from database.db import test_connection; import sys; sys.exit(0 if test_connection() else 1)"

CMD ["python", "main.py"]
