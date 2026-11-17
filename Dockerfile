FROM python:3.10-slim

RUN apt-get update && apt-get install -y ffmpeg git curl nodejs npm && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deno.land/install.sh | sh
ENV PATH="/root/.deno/bin:${PATH}"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil
WORKDIR /opt/bgutil/server
RUN npm install && npx tsc
WORKDIR /app

COPY . .
CMD ["python", "bot.py"]
