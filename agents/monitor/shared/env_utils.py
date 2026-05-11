"""환경변수 helper — agent shared 코드에서 공유.

본 디렉토리 helper 흐름 (`shared/__init__.py` map 참조):
  **본 파일** (env 검증) → ``auth_local`` (token 획득) → ``mcp_client`` (헤더 주입)
  → ``agent`` (tools 주입). 사용처: ``auth_local`` + ``mcp_client`` 내부.
"""
import os


def require_env(key: str) -> str:
    """env var 를 읽거나 친화적 RuntimeError 발생.

    deploy.sh 미실행 / .env 미로드 시 raw KeyError 대신 명확한 안내 메시지.
    """
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(
            f"환경변수 누락: {key}. deploy.sh 실행 후 .env 가 채워졌는지 확인."
        )
    return val
