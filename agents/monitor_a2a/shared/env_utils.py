"""환경변수 helper — agent shared 코드에서 공유."""
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
