FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app

# AWS_REGION 은 deploy_runtime.py 의 env_vars 가 주입 (hardcoded default 회피 — us-east-1 등 지원).
ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1 \
    PYTHONUNBUFFERED=1 \
    DOCKER_CONTAINER=1

COPY requirements.txt requirements.txt
RUN uv pip install -r requirements.txt

RUN uv pip install aws-opentelemetry-distro==0.12.2

RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

# A2A protocol Runtime — port 9000 root path
EXPOSE 9000

COPY . .

CMD ["opentelemetry-instrument", "python", "-m", "agentcore_runtime"]
