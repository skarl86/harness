# 품질 검증 리포트

## 자동 검증 결과
| 도구 | 상태 | 비고 |
|------|------|------|
| Syntax (verify --syntax) | Pass | wc.py, test_wc.py 구문 정상 |
| Test (unittest) | Pass | 5 tests in 0.001s (CountWords×3 + TextMode×1 + JsonMode×1) |
| Type Check | Skip | mypy 미설치 |
| Lint | Skip | ruff/flake8 미설치 |

## 수동 검증 결과
### 요구사항 충족도 (v2 기준)
- [x] stdin에서 텍스트 읽어 단어 빈도 출력
- [x] 빈도 내림차순, 동점 시 알파벳 오름차순
- [x] 기본 text 출력 `word: count`
- [x] `--json` 플래그로 JSON dict 출력 (정렬 순서 유지)
- [x] stdlib only
- [x] 빈 입력 → 빈 출력, exit 0

### 발견된 이슈
없음.

### 부가 검증
```
$ echo 'the quick brown fox the lazy the' | python3 wc.py
the: 3
brown: 1
fox: 1
lazy: 1
quick: 1

$ echo 'the quick brown fox the lazy the' | python3 wc.py --json
{"the": 3, "brown": 1, "fox": 1, "lazy": 1, "quick": 1}
```

## 수정 사항
없음.

## 최종 판정
**Pass**
