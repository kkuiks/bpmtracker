# 프로젝트 파일 검사

`project-contract.cjs`는 실제 프로젝트 validator를 사용해 정상 프로젝트와 잘못된 음원·트랙 참조, 소스 범위, 중복 ID를 확인합니다. 개인 음원이나 별도 라이브러리 없이 실행합니다.

```bash
node apps/daw/audit/project-contract.cjs
```

이 검사는 프로젝트 파일의 구조와 참조 계약을 다룹니다. 실제 재생과 분석의 실행 환경은 [앱 가이드](../README.md)에 설명되어 있습니다.
