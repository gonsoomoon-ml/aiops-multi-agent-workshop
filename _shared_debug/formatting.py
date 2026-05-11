"""ANSI 색 + 박스 helper + secret/JWT sanitize.

ANSI 상수 / 박스 보더 모티프는 dba ``shared/memory_hooks.py`` (lines 289-390) 차용
(https://github.com/gonsoomoon-ml/developer-briefing-agent).
워크샵 청중이 dba 와 동일한 화면 미감을 받도록 색·라벨 일관 유지.

dba 와 다른 점:
  - ``debug`` 인스턴스 플래그 대신 env ``DEBUG=1`` 단일 toggle (Runtime 호환)
  - JWT/secret sanitize helper 추가 (``mask``, ``redact_jwt``)
"""
import base64
import json
import os

# === 색 상수 (dba memory_hooks.py 와 동일 표) ===
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
BLUE = "\033[0;34m"
MAGENTA = "\033[0;35m"
CYAN = "\033[0;36m"
WHITE = "\033[0;37m"
DIM = "\033[2m"
NC = "\033[0m"

_COLOR_MAP = {
    "red": RED,
    "green": GREEN,
    "yellow": YELLOW,
    "blue": BLUE,
    "magenta": MAGENTA,
    "cyan": CYAN,
    "white": WHITE,
    "dim": DIM,
}


def is_debug() -> bool:
    """env ``DEBUG`` 가 truthy ('1' / 'true' / 'yes' / 'on') 면 활성."""
    return os.environ.get("DEBUG", "").lower() in ("1", "true", "yes", "on")


def dprint(label: str, body: str = "", color: str = "cyan") -> None:
    """단일 라벨 trace — DEBUG 꺼져있으면 no-op.

    Format: ``[DEBUG <label>] <body>`` (라벨/본문 동일 색).
    label 만 주고 body 생략하면 라벨만 출력.
    """
    if not is_debug():
        return
    c = _COLOR_MAP.get(color, CYAN)
    if body:
        print(f"\n{c}[DEBUG {label}] {body}{NC}")
    else:
        print(f"\n{c}[DEBUG {label}]{NC}")


def dprint_box(top_label: str, body: str | list[str], color: str = "magenta") -> None:
    """박스 보더로 감싼 multi-line dump (dba ``dump_prompt`` 박스 모티프).

    body 가 문자열이면 줄 단위 분할, list 면 그대로 사용.
    """
    if not is_debug():
        return
    c = _COLOR_MAP.get(color, MAGENTA)
    lines = body.split("\n") if isinstance(body, str) else body
    bar = "━" * max(2, 60 - len(top_label))
    print(f"\n{c}┏━━━ {top_label} {bar}{NC}")
    for line in lines:
        print(f"  {line}")
    print(f"{c}┗{'━' * 64}{NC}")


def mask(secret: str, keep: int = 4) -> str:
    """secret 의 마지막 N (기본 4) 자만 노출. 길이 < N+4 면 전체 가림."""
    if not secret:
        return "<empty>"
    if len(secret) < keep + 4:
        return "*" * len(secret)
    return f"…{secret[-keep:]} (len={len(secret)})"


def redact_jwt(token: str) -> dict:
    """JWT decode → 안전 claims 만 반환 (alg / kid / sub / aud / scope / iss / exp).

    base64url decode 후 header + payload 만 추출. signature 검증 X — debug 노출용.
    decode 실패 시 ``mask`` 결과만 포함.
    """
    if not token:
        return {"error": "empty_token"}
    parts = token.split(".")
    if len(parts) != 3:
        return {"error": "not_jwt", "preview": mask(token)}

    def _b64(seg: str) -> dict:
        seg += "=" * (-len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg))

    try:
        header = _b64(parts[0])
        payload = _b64(parts[1])
    except Exception as e:
        return {"error": f"decode_failed:{e}", "preview": mask(token)}

    safe = {
        "alg": header.get("alg"),
        "kid": header.get("kid"),
        "sub": payload.get("sub"),
        "aud": payload.get("aud") or payload.get("client_id"),
        "scope": payload.get("scope"),
        "iss": payload.get("iss"),
        "exp": payload.get("exp"),
    }
    return {k: v for k, v in safe.items() if v is not None}
