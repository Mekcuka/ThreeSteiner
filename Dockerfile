FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY topo_network ./topo_network
COPY examples/plan_prototype ./examples/plan_prototype

RUN pip install --no-cache-dir .

EXPOSE 8080

ENV TOPO_PLAN_BASE_DIR=

CMD ["uvicorn", "topo_network.api:app", "--host", "0.0.0.0", "--port", "8080"]
