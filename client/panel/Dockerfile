FROM python:3.12-slim

WORKDIR /app

# Ставим зависимости отдельным слоем: правки кода не пересобирают их заново
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Данные держим томом, иначе база пропадёт при обновлении образа
VOLUME ["/data"]
ENV PANEL_DATABASE_URL=sqlite:////data/panel.db

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
