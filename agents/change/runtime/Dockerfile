FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app

# All environment variables in one layer
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

# Signal that this is running in Docker for host binding logic
ENV DOCKER_CONTAINER=1

# Create non-root user
RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

# A2A protocol Runtime expects port 9000 root path (per AgentCore docs).
EXPOSE 9000

# Copy entire project (respecting .dockerignore)
COPY . .

# uvicorn 으로 직접 실행 (BedrockAgentCoreApp 미사용 — A2A 는 다른 protocol).
CMD ["opentelemetry-instrument", "python", "-m", "agentcore_runtime"]
