FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Catch syntax errors during image build instead of after deployment.
RUN python -m compileall -q app
CMD ["python", "-u", "-m", "app"]
