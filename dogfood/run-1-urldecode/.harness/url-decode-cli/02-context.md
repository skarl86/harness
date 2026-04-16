# 코드베이스 컨텍스트

## 프로젝트 개요
- 타입: **신규 프로젝트** (dogfood/run-1-urldecode/)
- 기술 스택: Python 3.9+, stdlib only
- 패키지 매니저: 없음 (단일 파일 스크립트)

## 디렉토리 구조
프로젝트 루트는 비어 있음. 결과물 생성 위치:
- `urldecode.py` (루트)
- `test_urldecode.py` (루트, 단위 테스트)

## 코드 컨벤션
신규 프로젝트이므로 컨벤션 새로 수립:
- 네이밍: snake_case 함수/변수, UPPER_SNAKE 상수
- 모듈 구조: 최상위 `main()` + 헬퍼 함수들
- docstring은 간단한 한 줄

## 관련 기존 코드
없음.

## 설정 및 환경
없음. `python3 urldecode.py < input.txt` 형태로 직접 실행.

## 의존성
stdlib: `sys`, `argparse`, `json`, `urllib.parse`.
