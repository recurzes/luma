FROM python:3.12-slim
LABEL authors="decurzion"
WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

CMD ["python", "-m", "app.bot"]