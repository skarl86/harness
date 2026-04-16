# 코드베이스 컨텍스트

## 프로젝트 개요
- 타입: **기존 프로젝트** (seed: notes.py + test_notes.py)
- 기술 스택: Python 3.9+, stdlib only
- 빌드/패키지: 없음 (단일 파일 CLI)

## 디렉토리 구조
```
notes.py           # CLI, 23 라인, add subcommand 하나
test_notes.py      # 2 tests (add_note 동작)
```

## 코드 컨벤션 (기존 파일에서 추출)
- 네이밍: snake_case 함수 / UPPER_SNAKE 상수 (예: `DEFAULT_NOTES_PATH`)
- 타입 힌트 사용: `Path`, `str`, 반환 `None` / `int`
- Docstring: 한 줄 `"""..."""`
- argparse: `sub.add_parser(...)` 패턴으로 subcommand 추가
- 파일 I/O: `with open(... encoding="utf-8")` 일관
- main entry: `if __name__ == "__main__": sys.exit(main())`

## 관련 기존 코드
- `add_note(text, notes_path)` — 파일 append 패턴. 새 헬퍼들도 동일 스타일로 작성:
  - `search_notes(notes_path, query, regex=False) -> list[tuple[int, str]]`
  - `list_notes(notes_path) -> list[tuple[int, str]]`
- `main()` 내부의 dispatch: `if args.cmd == "add": ...` → elif 체인 확장.

## 설정 및 환경
- `DEFAULT_NOTES_PATH = Path.home() / ".notes"`. CLI 플래그 `--notes-path`로 override 가능.

## 의존성
- stdlib: `argparse`, `sys`, `pathlib`. 추가로 `re` 필요 (--regex 구현).
