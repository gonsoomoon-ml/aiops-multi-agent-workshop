FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app

ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=1 \
    AWS_REGION=us-west-2 \
    AWS_DEFAULT_REGION=us-west-2

COPY requirements.txt requirements.txt
RUN uv pip install -r requirements.txt

RUN uv pip install aws-opentelemetry-distro==0.12.2

RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

EXPOSE 9000

COPY . .

CMD ["opentelemetry-instrument", "python", "-m", "agentcore_runtime"]
