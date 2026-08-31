FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]==3.2.3"
COPY db.py app.py ./
COPY data/ ./data/
COPY static/ ./static/
RUN useradd --create-home --uid 10001 astro && chown -R astro:astro /app
USER astro
EXPOSE 8080
CMD ["python", "app.py"]
