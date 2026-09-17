FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[stream]'
ENV HYDROPULSE_DATABASE_URL=postgresql+psycopg://hydropulse:hydropulse@postgres/hydropulse
CMD ["uvicorn","hydropulse.api:app","--host","0.0.0.0","--port","8000"]
