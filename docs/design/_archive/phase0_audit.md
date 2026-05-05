> ✅ **CLOSED — 2026-05-04** — 발견된 14건(B1~B6, C1~C8) 모두 해결. 본 문서는 결정 경로의 역사적 기록으로 보존됩니다. 최신 폴더 구조 / `deploy.sh` 상태는 코드와 `infra/phase0/README.md` 가 단일 진실 원천. 비결정 (사용자가 명시적으로 그대로 두기로 한 것) 없음.

# Phase 0 audit — folder structure + deploy.sh

**Date**: 2026-05-04 (opened) → 2026-05-04 (closed, 동일 일자)
**Status**: ✅ Closed. 8건 미정 → 8건 ✅ + 사전 자동 해결 6건 (B5, B6, C1~C4 D안 일괄 패치) = 14/14 ✅.

---

## A. 폴더 구조 — 강점

- 루트 코드 전용 컨벤션 (`agents/ chaos/ infra/ mock_data/ setup/ tests/`)
- `agents/monitor/{prompts,tools}` per-agent 분리 — 향후 Incident/Change/Supervisor 동일 패턴 가능
- `infra/phase0/` phase-namespaced
- `docs/{design,research}` 비코드 분리

## B. 폴더 구조 — 발견 이슈

| # | 이슈 | 심각도 | 처방 후보 | 결정 |
|---|---|---|---|---|
| B1 | `local_run.py` + `agent.py` 동거. Phase 3 Runtime 엔트리 추가 시 셋이 한 폴더 | 中 | ~~`shared/` + `local/` (+ Phase 3 시 `runtime/`)~~ → 적용 (2026-05-04) | ✅ 해결 |
| B2 | `setup.sh` (파일) vs `setup/` (디렉토리) 공존 — newcomer 혼동 | 低 | ~~rename `setup.sh` → `bootstrap.sh`~~ → 적용 (2026-05-04) | ✅ 해결 |
| B3 | `infra/phase0/`에 `README.md` 없음 (구성/비용/배포 개요 부재) | 中 | ~~README.md 추가 (구성/배포/검증/정리 4섹션) + VERIFICATION.md 흡수~~ → 적용 (2026-05-04) | ✅ 해결 |
| B4 | `docs/design/plan.md`, `plan.v1-single-agent.md` legacy 표시 X | 中 | ~~`_archive/` 이동 + DEPRECATED 헤더~~ → 적용 (2026-05-04) | ✅ 해결 |
| B5 | `mock_data/` phase scope 표시 X. Phase 1 전용 | 低 | ~~`mock_data/phase1/`~~ → 적용 (2026-05-04) | ✅ 해결 |
| B6 | `chaos/` Phase 0 종속인데 루트에 있음. `infra/phase0/chaos/` 가 응집 | 低 | ~~이동~~ → 적용 (2026-05-04) | ✅ 해결 |

## C. `infra/phase0/deploy.sh` — 발견 이슈

| # | 이슈 | 심각도 | 처방 | 결정 |
|---|---|---|---|---|
| C1 | 사전 AWS creds 검증 없음. CFN 단계에서 늦게 fail | 中 | ~~`aws sts get-caller-identity`~~ → 적용 (2026-05-04) | ✅ 해결 |
| C2 | IP 자동 감지 실패 시 unclear 에러 | 中 | ~~`[[ -z "$MY_IP" ]] && fail`~~ → 적용 (2026-05-04) | ✅ 해결 |
| C3 | `.env` 없을 때 silent skip | 中 | ~~`.env.example` 자동 복사~~ → 적용 (2026-05-04) | ✅ 해결 |
| C4 | 부팅 대기 안내 없음 | 中 | ~~`⏳ Flask 부팅 ~2-3분` + `get-console-output`~~ → 적용 (2026-05-04) | ✅ 해결 |
| C5 | KeyPair PEM 추출 명령 안내 없음 | 低 | ~~deploy.sh 출력 + README § 2-1~~ → 적용 (2026-05-04) | ✅ 해결 |
| C6 | stack name 하드코딩 — 동시 사용자 충돌 | 低 | ~~`DEMO_USER` 도입 + stack/keypair/태그에 포함 + Export 제거~~ → 적용 (2026-05-04) | ✅ 해결 |
| C7 | `AWS::EC2::EIP` + `InstanceId` 직접 참조 (deprecated 패턴) | 低 | ~~`EIPAssociation` 분리 + Output `!GetAtt EIP.PublicIp`~~ → 적용 (2026-05-04) | ✅ 해결 |
| C8 | `bootstrap.sh`의 `uv sync`가 dev 의존성(pytest/ruff) 제거 — Phase 1 검증 후 다시 부트스트랩 돌리면 pytest 사라짐 | 中 | ~~PEP 735 `[dependency-groups] dev` 로 이동 — `uv sync` 만으로 dev 자동 포함~~ → 적용 (2026-05-04) | ✅ 해결 |

## D. 추천 최소 패치 (D안 — 4줄 변경)

C1~C4 만 적용. fail-fast + audience 친화 안전망.

```bash
# C1
aws sts get-caller-identity --query Account --output text >/dev/null \
    || fail "AWS 자격증명 미설정"

# C2 (MY_IP 줄 다음)
[[ -z "$MY_IP" ]] && fail "IP 자동 감지 실패. ALLOWED_SSH_IP=x.x.x.x/32 export 후 재실행"

# C3 (.env 로드 직전)
[[ ! -f "$PROJECT_ROOT/.env" ]] && cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"

# C4 (마지막)
echo "  ⏳ Flask 부팅 ~2-3분. 그 후: curl http://$PUBLIC_IP:8080/health"
echo "  부팅 디버깅: aws ec2 get-console-output --instance-id $INSTANCE_ID --region $REGION --output text"
```

## E. 진행 옵션 (요약)

- (가) C1~C4 패치 → deploy (제 추천)
- (나) B3 README + C1~C4 → deploy
- (다) 전부 다 고치고 → deploy (작업량 큼)
- (라) 패치 없이 deploy

## 참고 — 즉시 영향 없는 정보

- AWS Account `<ACCOUNT_ID>` (Administrator) 검증 완료 (bootstrap.sh 5단계 통과)
- GitHub PAT SSM 저장 완료: `/aiops-demo/github-token`
- `.env` 생성됨 (`AWS_REGION=us-west-2`)
- 다음 명령: `bash infra/phase0/deploy.sh` (대기 중)
