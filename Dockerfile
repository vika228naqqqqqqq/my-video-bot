FROM python:3.10-slim

# Добавляем unzip в список устанавливаемых пакетов
RUN apt-get update && apt-get install -y ffmpeg git curl nodejs npm unzip && rm -rf /var/lib/apt/lists/*

# Устанавливаем Deno в системную папку
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh
ENV PATH="/usr/local/bin:${PATH}"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Клонируем и собираем PO Token Provider (генератор токенов)
RUN git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil
WORKDIR /opt/bgutil/server
RUN npm install && npx tsc
WORKDIR /app

COPY . .

CMD ["python", "bot.py"]
