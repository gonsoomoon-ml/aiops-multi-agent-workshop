# Workshop 환경 구성 — CloudShell + Self-Deploy 방식

> **AWS CloudShell** 로 레포를 받아 VSCode Server(code-server) EC2 를 직접 배포하고, **Claude Code on Amazon Bedrock** 을 설정하는 가이드입니다.

## 사전 조건

- AWS Management Console 에 로그인 가능한 계정 (CloudShell 사용 가능 region — 예: `us-east-1`)
- 해당 계정에서 EC2 / CloudFormation / IAM Role 을 생성할 수 있는 권한
- Amazon Bedrock 모델 액세스 활성화 (Anthropic Claude 계열 — 본 워크샵 region 은 `us-east-1` 고정)

> ⚠️ **Region 고정**: 배포 스크립트는 `us-east-1` 에 고정되어 있습니다. CloudShell 도 화면 우측 상단에서 **N. Virginia (us-east-1)** 로 맞춰주세요.

---

## 전체 흐름

```
CloudShell ──[1] 레포 clone──> [2] deploy.sh 실행 ──> VSCode EC2 배포
                                                           │
브라우저 ──[3] https://<IP>:8888 접속 ─────────────────────┘
   │
VSCode 터미널 ──[4] 레포 clone ──> [5] setup-claude-bedrock.sh ──> Claude Code on Bedrock
                                          │
                          [6] Bedrock 콘솔에서 short-term API key 복사 후 입력
```

---

## 1. CloudShell 열기 & 레포 clone

### Step 1 — CloudShell 진입

AWS Console 우측 상단의 **CloudShell 아이콘**(`>_`)을 클릭하세요. region 이 **us-east-1 (N. Virginia)** 인지 확인합니다.

> CloudShell 에는 `git`, `aws` CLI, `python3` 이 기본 설치되어 있어 추가 설치가 필요 없습니다.

### Step 2 — 레포 clone

CloudShell 터미널에서 아래 명령을 실행하세요.

```bash
git clone https://github.com/gonsoomoon-ml/aiops-multi-agent-workshop.git
```

---

## 2. VSCode Server EC2 배포 (deploy.sh)

### Step 1 — 배포 스크립트 실행

```bash
bash aiops-multi-agent-workshop/infra/vscode/deploy.sh
```

### Step 2 — 설정값 입력

스크립트가 순서대로 물어봅니다. 각 항목에 입력하세요.


| 프롬프트                       | 입력값                                      | 비고                                               |
| ------------------------------ | ------------------------------------------- | -------------------------------------------------- |
| `Stack Name`                   | 원하는 스택 이름 (예:`aiops-vscode-홍길동`) | 여러 사용자가 같은 계정을 쓰면 **각자 다른 이름** |
| `VSCode 비밀번호 (8자 이상)`   | 8자 이상 비밀번호                           | 브라우저 접속 시 사용                              |
| `비밀번호 확인`                | 위와 동일하게 재입력                        |                                                    |
| `인스턴스 타입 선택`           | 번호 입력`[1]` (Enter = `t3.2xlarge`)       | 기본값 권장                                        |
| `EBS 볼륨 크기 (GB)`           | Enter =`20`                                 |                                                    |
| `VPC 선택`                     | 번호 입력`[1]` (Enter = Default VPC)        | Public Subnet 은 자동 탐색                         |
| `배포를 시작할까요? (y/n) [y]` | `y`                                         |                                                    |


### Step 3 — 배포 완료 & 접속 정보 확인

약 3–5분 후 아래와 같은 출력이 나옵니다.

```
=================================================================
   배포 완료 / Deployment Complete
=================================================================

  ┌─────────────────────────────────────────────────┐
  │  접속 방법                                       │
  ├─────────────────────────────────────────────────┤
  │  VSCode Server (브라우저)
  │  URL: https://<PUBLIC_IP>:8888
  │  비밀번호: 설정한 비밀번호
  │  ...
  └─────────────────────────────────────────────────┘

  EC2 UserData 설치 완료까지 약 5-10분 소요됩니다.
```

출력된 **`URL` (`https://<PUBLIC_IP>:8888`)** 을 복사해 두세요.

> ⏳ **중요**: 스택 배포가 끝나도 EC2 내부에서 code-server / Claude Code 확장 설치(UserData)에 추가로 **약 5–10분**이 더 걸립니다. 잠시 기다린 뒤 브라우저로 접속하세요.

---

## 3. VSCode Server 접속

브라우저에서 위에서 복사한 **`https://<PUBLIC_IP>:8888`** 로 접속하세요.

> 🔒 self-signed 인증서를 사용하므로 브라우저에 **"연결이 비공개로 설정되어 있지 않습니다"** 경고가 나올 수 있습니다.
> **고급(Advanced) → 계속 진행(Proceed to ...)** 을 클릭하세요. (워크샵용 임시 인증서라 안전합니다.)

비밀번호 입력 화면이 나오면 **2단계에서 설정한 VSCode 비밀번호**를 입력하세요.

접속 후 상단 메뉴 **Terminal → New Terminal** 로 터미널을 여세요.

---

## 4. VSCode 터미널에서 레포 clone

VSCode(EC2) 안에는 아직 워크샵 레포가 없으므로 다시 clone 합니다.

```bash
cd ~ && git clone https://github.com/gonsoomoon-ml/aiops-multi-agent-workshop.git
```

clone 이 끝나면 VSCode 좌측 **File → Open Folder** 로 `/home/ec2-user/aiops-multi-agent-workshop` 를 열어두면 이후 실습이 편리합니다.

---

## 5. Claude Code on Bedrock 설정 (setup-claude-bedrock.sh)

### Step 1 — Bedrock short-term API key 발급

먼저 토큰을 발급받습니다. 브라우저 새 탭에서:

1. **Amazon Bedrock 콘솔** 로 이동 (region: `us-east-1`)
2. 좌측 메뉴 하단 **API keys** 클릭
3. **Short-term API keys** 탭 선택 → **Generate short-term API key** 클릭
4. 생성된 키를 **복사** (`bedrock-api-key-...` 형태)

> ⏰ short-term API key 는 최대 **12시간** 유효하므로 워크샵 1회 진행에 충분합니다.
> 만료되면 다시 발급받아 본 스크립트를 재실행하면 됩니다.

### Step 2 — 설정 스크립트 실행

VSCode(EC2) 터미널에서 실행하세요.

```bash
bash ~/aiops-multi-agent-workshop/infra/vscode/setup-claude-bedrock.sh
```

### Step 3 — 값 입력

스크립트가 순서대로 물어봅니다.


| 프롬프트                                         | 입력값                                                     |
| ------------------------------------------------ | ---------------------------------------------------------- |
| `AWS_BEARER_TOKEN_BEDROCK 값을 입력하세요`       | **Step 1 에서 복사한 Bedrock short-term API key** 붙여넣기 |
| `사용할 모델을 선택하세요 (1 또는 2, 기본값: 1)` | `1` = Sonnet 4.6 (권장) / `2` = Opus 4.6                   |
| `Max Output Tokens (1, 2 또는 3, 기본값: 1)`     | `2` (16384, 일반 개발 작업) 권장                           |

스크립트는 다음 두 곳을 자동으로 설정합니다.

- `~/.bashrc` — 터미널용 환경변수 (`CLAUDE_CODE_USE_BEDROCK=1` 등)
- code-server `settings.json` — VSCode 내 Claude Code 확장용 환경변수

완료되면 아래 메시지가 나옵니다.

```
==========================================
 설정이 완료되었습니다!
==========================================
```

### Step 4 — 설정 적용

터미널에서 `claude` CLI 를 사용하기 위해 터미널 환경변수를 적용합니다.

```bash
source ~/.bashrc
```

---

## 6. 동작 확인

VSCode 좌측 액티비티 바의 **Claude** 아이콘을 클릭하거나, 터미널에서 아래를 실행하세요.

```bash
claude
```

별도 로그인 없이 Claude Code 가 바로 실행되면(Bedrock 인증 통과) 설정이 완료된 것입니다.
간단히 프롬프트를 입력해 응답이 오는지 확인하세요.

> ❌ 인증 오류가 난다면: ① short-term API key 만료(재발급), ② region 이 `us-east-1` 인지, ③ Bedrock 모델 액세스가 활성화되어 있는지 확인하세요.

---

## 7. 다음 단계

→ [`phase0.md`](phase0.md) — EC2 시뮬레이터 + CloudWatch Alarm 배포

---

## 부록 — 정리(teardown)

워크샵이 끝나면 VSCode EC2 스택을 삭제하세요. **CloudShell** 에서 실행합니다.

```bash
bash aiops-multi-agent-workshop/infra/vscode/deploy.sh --delete <Stack Name>
```

> `<Stack Name>` 은 2단계에서 입력한 스택 이름입니다. 워크샵에서 배포한 다른 리소스(EC2 시뮬레이터, AgentCore 등)는 각 phase 문서 또는 `teardown_all.sh` 를 참고해 별도로 정리하세요.
