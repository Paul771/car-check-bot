FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot code
COPY bot/ ./bot/
COPY .env ./

# Run the bot
CMD ["python", "-m", "bot.main"]