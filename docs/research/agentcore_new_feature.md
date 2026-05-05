AWS에서 AgentCore의 새로운 기능 4가지를 발표했습니다. 에이전트 개발부터 배포·운영까지의 진입장벽을 대폭 낮추는 업데이트입니다.

:one: Managed Agent Harness Preview
오케스트레이션 코드 없이, 모델·도구·지시사항만 선언하면 API 호출 3번으로 에이전트 배포가 가능합니다. 요구사항이 복잡해지면 동일한 플랫폼에서 config → code 기반으로 전환할 수 있습니다.
:round_pushpin: US West (Oregon), US East (N. Virginia), Asia Pacific (Sydney), Europe (Frankfurt)

:two: AgentCore CLI GA
터미널 하나에서 프로토타입 → 배포 → 운영을 통합 관리합니다. CDK 기반 IaC를 지원하며 Terraform도 곧 지원 예정입니다. 로컬에서 테스트한 설정이 프로덕션과 동일하게 동작합니다.

:three: Persistent Agent Filesystem GA
세션 상태를 내구성 파일시스템에 영속화하여, 에이전트가 작업 중간에 중단했다가 정확히 같은 지점에서 재개할 수 있습니다. 별도 코드 없이 Human-in-the-loop 패턴을 바로 적용할 수 있습니다.

:four: Pre-built Skills for Coding Agents 4월 말 출시 예정
AI 코딩 어시스턴트에 AgentCore 베스트 프랙티스를 주입하는 스킬 팩입니다. Kiro에는 이미 내장되어 있고, Claude Code·Codex·Cursor용 플러그인은 4월 말 제공 예정입니다.

:bulb: CLI, Harness, Skills 모두 추가 과금 없이 사용 가능합니다.:paperclip: 블로그 원문: https://aws.amazon.com/blogs/machine-learning/get-to-your-first-working-agent-in-minutes-announcing-new-features-in-amazon-bedrock-agentcore/