# 요구사항 분석

## 요청 요약
stdin에서 URL-encoded 문자열을 줄 단위로 읽어 디코딩해 출력하는 Python CLI. `--json` 플래그로 `{input, decoded}` JSON 객체 출력 모드 지원.

## 논의점

### 1. 구현가능성
- Python stdlib의 `urllib.parse.unquote` / `unquote_plus`로 디코딩 가능.
- 표준 입력 스트리밍만으로 충분 — 외부 라이브러리 불필요.
- 단일 파일 CLI(`urldecode.py`)로 충분한 스코프.

### 2. UX
- 입력: `echo 'a%20b%2Bc' | python3 urldecode.py` → `a b+c`
- JSON 모드: `python3 urldecode.py --json` → `{"input":"a%20b%2Bc","decoded":"a b+c"}`
- 빈 줄은 빈 줄로 그대로 통과할지? → 제안: 건너뛴다.

### 3. 디코딩 방식
- `unquote` vs `unquote_plus`: 쿼리스트링 스타일(`+` → 공백)은 `unquote_plus`. 일반 URL 디코딩은 `unquote`. 기본값은 `unquote`로 하고 향후 플래그 고려.

### 4. 에러 처리
- 디코딩 실패는 거의 없지만(unquote는 관대함), UnicodeDecodeError 가능. 실패 시 해당 줄 건너뛰고 stderr에 경고 출력.

### 5. 테스트
- stdin 모킹은 `io.StringIO` + `argparse.parse_args` 주입.
- 단위 테스트로 `unittest` 사용, 빌드 없음.

## 초기 기술 판단
- 예상 기술 스택: Python 3.9+, stdlib only
- 예상 복잡도: 낮음
- 핵심 리스크: 없음 (stdlib만 사용, 단일 파일)

## 사용자 피드백
- 최소 구현: stdlib만, 외부 의존성 없음.
- 빈 줄은 스킵.
- 디코딩은 `unquote` (쿼리스트링용 `+→공백`은 필요 없음, 그냥 URL 디코딩).
