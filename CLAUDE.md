# Project conventions for Claude

본 프로젝트 (AIOps multi-agent demo, AWS Bedrock AgentCore Runtime + Strands + A2A) 의 코드 작성 / 리뷰 / 문서화 컨벤션. Claude 가 새 파일 작성 또는 기존 파일 수정 시 본 규약을 따름.

## 1. 언어 (Korean-friendly 원칙)

| 영역 | 언어 |
|---|---|
| 사용자와의 대화 (review prose, summary, options) | **한국어** |
| 코드 docstring | **한국어** (1-2 문장 한국어 narration; 기술용어는 영어 그대로) |
| 코드 inline comment | **한국어 prose + 영어 기술용어 mix** (예: `# base64 decode (vnd.github.raw 와 다른 endpoint)`) |
| 코드 identifier (var, func, class) | 영어 |
| 파일 경로 | 영어 |
| Git commit message | 영어 (단 본문에 한국어 주석 가능) |
| Log message (println / printf) | **한국어** + emoji + ANSI color (워크샵 청중) |
| User-facing 에러 메시지 | **한국어** (예: `"DEMO_USER 미설정"`) |
| 디자인 문서 (`docs/design/*.md`) | **한국어** |
| README.md | **한국어** prose + 영어 코드 블록 |
| AWS resource 이름 (Role 명, function 명) | 영어 (AWS API 매칭) |

**의도**: 워크샵 청중 (한국어 사용자) 이 코드를 읽어가며 학습할 때, 주석/메시지가 한국어이면 학습 효율 ↑. 코드 식별자는 영어 — Bedrock/AWS API/Python 표준 정합.

**예시** (Phase 6a Lambda handler):
```python
def _get_token() -> str:
    """SSM SecureString 으로부터 GitHub PAT 조회 (lazy + cached). 'repo' full scope 필요."""
    global _token_cache
    if _token_cache:
        return _token_cache
    ssm = boto3.client("ssm")
    # 모듈 전역 cache — Lambda warm container 재사용 시 SSM 호출 절감
    ...
```

## 2. dba 패턴 (AgentCore Runtime/deploy/invoke 스크립트)

`developer-briefing-agent/managed-agentcore/` 가 canonical reference. 자세한 내용 [`memory/dba_pattern_for_runtime_code.md`](.claude/projects/-home-ubuntu-aiops-multi-agent-demo/memory/dba_pattern_for_runtime_code.md) 참고. 요약:
- 함수명: action verb (`copy_shared_into_build_context`), `step1_X` 같은 numeric prefix 금지.
- 모듈 docstring: 한국어 multi-section (한 줄 정의 / 사용법 / 사전 조건 / 수행 단계 / reference).
- Print: 한국어 + emoji (`✅`, `❌`, `⏳`) + ANSI color.
- `os.chdir(SCRIPT_DIR)` at top of deploy scripts.

## 3. Phase preservation rule

이전 phase 의 코드 (`agents/monitor/`, `agents/incident/`, `infra/{ec2-simulator,cognito-gateway,github-lambda}/`, etc.) 는 후속 phase 작업 중 **수정 금지**. 새 phase 의 코드는 신규 디렉토리 (예: `agents/monitor_a2a/`, `agents/incident_a2a/`) 로 작성.

**의도**: 워크샵 청중이 Phase N-1 (working) 와 Phase N (new pattern) 을 side-by-side 비교 가능하도록.

**예외**: `docs/`, `pyproject.toml`, `.gitignore` (additive only). 자세한 내용 [`memory/feedback_preserve_previous_phase_code.md`](.claude/projects/-home-ubuntu-aiops-multi-agent-demo/memory/feedback_preserve_previous_phase_code.md).

## 4. 파일 단위 review

코드 리뷰 시:
- **파일 1개씩** 다룸 (한 번에 여러 파일 X).
- 우려사항 **번호** 매겨 제시 (S1, S2, ... 또는 H1, H2, ...).
- 사용자 결정 받기 전 자율 수정 **금지**.
- 사용자 명시 후에만 수정. "approved" 또는 "fix S1" 같은 명시.

자세한 내용 [`memory/review_style.md`](.claude/projects/-home-ubuntu-aiops-multi-agent-demo/memory/review_style.md).

## 5. AWS resource 생성 명령 (deploy/teardown/launch)

자원을 실제로 만들거나 변경하는 명령 (예: `bash deploy.sh`, `cfn deploy`, `Runtime.launch`, `aws ssm put-parameter`, `aws iam create-*`) 은 **사용자가 직접 실행**.

Claude 는 single-line copy-paste-safe 명령 제공 후 멈춤. 백슬래시 line continuation 회피 (paste 시 깨짐). 자세한 내용 [`memory/feedback_user_runs_deploy_commands.md`](.claude/projects/-home-ubuntu-aiops-multi-agent-demo/memory/feedback_user_runs_deploy_commands.md).

read-only AWS 호출 (`get-parameter`, `list-*`, `describe-*`, `get-caller-identity`) 은 Claude 가 검증/탐색용으로 자유 호출.

## 6. Educational scope

본 프로젝트의 목적은 **Strands Agent SDK + AWS Bedrock AgentCore** 학습. IAM/Lambda/Cognito 같은 plumbing 은 CFN (yaml) 로 유지 — boto3/SDK 변환 제안 금지 (re-expose plumbing 회피). 자세한 내용 [`memory/project_educational_scope.md`](.claude/projects/-home-ubuntu-aiops-multi-agent-demo/memory/project_educational_scope.md).

## reference

- `docs/design/plan_summary.md` — 전체 phase 진행 상황
- `docs/design/phase{N}.md` — phase 별 설계 (D1~D10 의사결정 로그)
- `docs/research/a2a_intro.md` — A2A 프로토콜 직관적 학습
- `developer-briefing-agent/` (외부) — dba 패턴 canonical reference
