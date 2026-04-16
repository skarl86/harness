# 품질 검증 리포트

## 자동 검증 결과
| 도구 | 상태 | 비고 |
|------|------|------|
| Syntax (py_compile) | Pass | urldecode.py, test_urldecode.py 모두 파싱 |
| Test (unittest) | Pass | 5 tests in 0.001s |
| Type Check | Skip | mypy 미설치 |
| Lint | Skip | ruff/flake8 미설치 |

## 수동 검증 결과
### 요구사항 충족도
- [x] stdin에서 URL-encoded 문자열 읽기
- [x] 줄 단위 디코딩 출력
- [x] `--json` 플래그: `{input, decoded}` 형태
- [x] 빈 줄 스킵
- [x] stdlib only

### 발견된 이슈
없음.

## 수정 사항
없음.

## 최종 판정
**Pass**
