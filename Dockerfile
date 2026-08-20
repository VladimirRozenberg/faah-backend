FROM python:3.11-slim

WORKDIR /app

# Copy dependencies first (for caching)
COPY requirements.txt .

# Install Python dependencies (no system packages needed)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the port
EXPOSE 8000

# Run the app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
