FROM python:3.12-slim

# Чтобы вывод логов сразу шёл в консоль
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Сначала зависимости — так быстрее будут пересобираться образы
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Потом весь код
COPY . .

# Запуск бота
CMD ["python", "run.py"]
