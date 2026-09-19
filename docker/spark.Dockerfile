FROM apache/spark:3.5.6-scala2.12-java17-python3-ubuntu
USER root
WORKDIR /app
COPY src ./src
COPY docker/spark_dependency_probe.py /tmp/spark_dependency_probe.py
# Spark's bundled Python is 3.10; install the small runtime subset directly
# rather than the application package, whose native worker requires Python 3.12+.
RUN pip install --no-cache-dir \
    'sqlalchemy==2.0.43' \
    'psycopg[binary]==3.2.10' \
    'pydantic-settings==2.10.1' \
    'kafka-python==2.2.15'
RUN mkdir -p /opt/spark/ivy && \
    /opt/spark/bin/spark-submit \
      --master 'local[1]' \
      --conf spark.jars.ivy=/opt/spark/ivy \
      --packages org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.6 \
      /tmp/spark_dependency_probe.py && \
    cp /opt/spark/ivy/jars/*.jar /opt/spark/jars/
ENV PYTHONPATH=/app/src
USER spark
