FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# requirements.txt installs the Bocha MCP package directly from Git.
RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY main.py ./
COPY app ./app
# DeepAgent loads domain workflows from the read-only virtual /skills tree at
# runtime.  Keeping Skills outside the image silently works in local source
# runs but makes both ShoppingAgent and KnowledgeAgent fail in production.
COPY skills ./skills

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
