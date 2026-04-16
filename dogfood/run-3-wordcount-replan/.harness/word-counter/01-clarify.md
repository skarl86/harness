# 요구사항 분석

## 요청 요약
stdin으로 텍스트를 받아 단어별 빈도를 출력하는 Python CLI.

## 논의점

### 1. 단어 분리 규칙
- 기본: 공백(whitespace) + 구두점 제거 후 소문자화. `re.findall(r"\w+", text.lower())` 패턴.
- 숫자 포함 토큰도 단어로 간주? → 기본 yes (한 토큰으로 처리).

### 2. 출력 형식
- 기본: `word: count` 한 줄씩, 빈도 내림차순, 동점 시 알파벳 순.
- 향후 JSON 형식 필요 여부는 사용자에게 확인.

### 3. 빈 입력 처리
- 빈 stdin → 빈 출력, exit 0.

### 4. 테스트
- `io.StringIO` 주입으로 main 테스트.
- 직접 호출 가능한 `count_words(text: str) -> dict` 헬퍼로 단위 테스트.

## 초기 기술 판단
- 예상 기술 스택: Python 3.9+, stdlib only (`re`, `collections.Counter`)
- 예상 복잡도: 낮음
- 핵심 리스크: 없음

## 사용자 피드백
- 단어 분리 규칙 OK.
- 출력 형식: **우선 텍스트만**. JSON 모드는 일단 빼고 진행.
- 빈 입력 처리 OK.
