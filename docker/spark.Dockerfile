FROM apache/spark:3.5.6-scala2.12-java17-python3-ubuntu
USER root
WORKDIR /app
COPY src ./src
# Spark's bundled Python is 3.10; install the small runtime subset directly
# rather than the application package, whose native worker requires Python 3.12+.
RUN pip install --no-cache-dir \
    'sqlalchemy==2.0.43' \
    'psycopg[binary]==3.2.10' \
    'pydantic-settings==2.10.1' \
    'kafka-python==2.2.15'
ENV PYTHONPATH=/app/src
USER spark
