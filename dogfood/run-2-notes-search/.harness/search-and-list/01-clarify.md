# 요구사항 분석

## 요청 요약
기존 `notes.py` CLI에 `search`와 `list` 서브커맨드를 추가한다. search는 쿼리 매칭 (선택적 --regex), list는 라인 번호와 함께 전체 출력.

## 논의점

### 1. 기존 구조 승계
- `notes.py`는 이미 `add` 서브커맨드 구조로 argparse subparsers를 쓰고 있음 → 동일 패턴으로 확장.
- `add_note(text, notes_path)` 헬퍼 패턴을 따라 `search_notes(...)`, `list_notes(...)` 헬퍼 추가.

### 2. search 의미론
- 기본: 대소문자 구분 없는 부분 문자열 포함 매치. 이유: 일반 메모의 UX 기대에 맞음.
- `--regex`: `re.search` 기반. 대소문자 옵션은 기본 무시(IGNORECASE) 또는 추가 `--case`? 이번 스코프에선 기본 case-insensitive 고정.
- 출력 형식: `라인번호: 내용`

### 3. list 의미론
- 모든 노트를 `1: first line\n2: second line\n...` 형태로 출력.
- 노트 파일이 없으면 빈 출력 (오류 아님).

### 4. 테스트
- 기존 `test_notes.py`에 `TestSearch`, `TestList` 클래스 추가.
- 기존 `TestAddNote` 영향 없음 — 회귀 방지를 위해 전체 테스트 수행.

### 5. 병렬 가능성
- `search_notes`와 `list_notes` 헬퍼는 서로 독립적 → 병렬 Task 후보.
- 단, **같은 파일(`notes.py`)을 수정**하므로 harness CLI의 conflicts가 감지해 순차로 강등해야 함. 좋은 검증 기회.

## 초기 기술 판단
- 예상 기술 스택: Python 3.9+, stdlib only (기존 패턴 계승)
- 예상 복잡도: 낮음
- 핵심 리스크: 기존 `notes.py`의 `add_note` 손상. 테스트로 회귀 검증 필수.

## 사용자 피드백
- 병렬 시도 후 conflicts 감지되면 순차로 진행, 명시적으로 flow에 포함.
- --regex 기본 case-insensitive 동의.
- 기존 테스트는 손대지 말고 새 클래스만 추가.
