# 01. Python 기초 — 자료구조, 문자열, 파일 I/O, 정규표현식

> **TL;DR**
> - 코딩 테스트에서 가장 자주 쓰이는 Python 자료구조는 **list, dict, set**이며, 각각의 시간복잡도를 이해해야 한다.
> - 문자열 처리(split, join, f-string)와 **정규표현식(re 모듈)**은 DevOps 스크립팅에서도 실무 그대로 출제된다.
> - 파일 I/O는 `with open()` 패턴만 확실히 익히면 로그 파싱, 설정 파일 처리 문제에 바로 대응 가능하다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 30min

---

## 핵심 개념

### 1. List — 순서가 있는 가변 시퀀스

```python
# 생성과 기본 연산
servers = ["web-01", "web-02", "db-01"]
servers.append("cache-01")          # O(1) 끝에 추가
servers.insert(0, "lb-01")          # O(n) 앞에 삽입 — 느림!
servers.remove("db-01")             # O(n) 값으로 삭제

# 슬라이싱 — 코딩테스트 필수
logs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
recent = logs[-3:]                  # [8, 9, 10] 최근 3개
every_other = logs[::2]             # [1, 3, 5, 7, 9] 짝수 인덱스

# List Comprehension — 한 줄 필터링
error_logs = [line for line in logs if line > 5]

# 정렬
servers.sort()                      # in-place, O(n log n)
sorted_servers = sorted(servers)    # 새 리스트 반환
```

**시간복잡도 요약:**

| 연산 | 시간복잡도 | 비고 |
|------|-----------|------|
| `append()` | O(1) | 끝에 추가 |
| `insert(0, x)` | O(n) | 앞에 삽입 |
| `x in list` | O(n) | 순차 탐색 |
| `sort()` | O(n log n) | Timsort |
| 인덱스 접근 `[i]` | O(1) | 직접 접근 |

### 2. Dict — 해시맵 기반 Key-Value 저장소

```python
# 서버 상태 관리
server_status = {
    "web-01": "healthy",
    "web-02": "unhealthy",
    "db-01": "healthy"
}

# 안전한 접근 — KeyError 방지
status = server_status.get("web-03", "unknown")  # "unknown"

# 순회 패턴
for host, status in server_status.items():
    print(f"{host}: {status}")

# defaultdict — 집계에 최적
from collections import defaultdict, Counter

error_count = defaultdict(int)
errors = ["timeout", "500", "timeout", "403", "500", "500"]
for err in errors:
    error_count[err] += 1
# {'timeout': 2, '500': 3, '403': 1}

# Counter — 더 간결한 집계
count = Counter(errors)
print(count.most_common(2))  # [('500', 3), ('timeout', 2)]
```

**시간복잡도 요약:**

| 연산 | 시간복잡도 |
|------|-----------|
| `dict[key]` | O(1) 평균 |
| `key in dict` | O(1) 평균 |
| `dict.items()` | O(n) |
| `dict.get(k, default)` | O(1) 평균 |

### 3. Set — 중복 제거와 집합 연산

```python
# 중복 제거
all_ips = ["10.0.1.1", "10.0.1.2", "10.0.1.1", "10.0.1.3"]
unique_ips = set(all_ips)  # {'10.0.1.1', '10.0.1.2', '10.0.1.3'}

# 집합 연산 — 인프라 비교에 유용
prod_servers = {"web-01", "web-02", "db-01", "cache-01"}
monitored = {"web-01", "db-01", "cache-01"}

unmonitored = prod_servers - monitored          # {'web-02'}
common = prod_servers & monitored               # {'web-01', 'db-01', 'cache-01'}
all_servers = prod_servers | monitored           # 합집합

# 존재 확인 O(1) — list의 O(n)보다 훨씬 빠름
if "web-01" in prod_servers:
    print("서버 존재 확인")
```

### 4. 문자열 처리 — split, join, f-string

```python
# 로그 라인 파싱
log_line = "2024-01-15 10:23:45 ERROR [web-01] Connection timeout to db-01"
parts = log_line.split()
timestamp = f"{parts[0]} {parts[1]}"    # "2024-01-15 10:23:45"
level = parts[2]                         # "ERROR"
server = parts[3].strip("[]")           # "web-01"

# join으로 조합
tags = ["env:prod", "service:api", "region:kr"]
tag_string = ",".join(tags)  # "env:prod,service:api,region:kr"

# f-string 포맷팅
cpu_usage = 87.3
alert = f"CPU usage: {cpu_usage:.1f}% — {'CRITICAL' if cpu_usage > 80 else 'OK'}"

# 문자열 메서드 체이닝
raw = "  Hello, World!  "
cleaned = raw.strip().lower().replace(",", "")  # "hello world!"

# startswith / endswith — 파일 필터링
files = ["app.py", "config.yaml", "deploy.sh", "test_app.py", "README.md"]
python_files = [f for f in files if f.endswith(".py")]
test_files = [f for f in files if f.startswith("test_")]
```

### 5. 파일 I/O — with open 패턴

```python
# 파일 읽기 — 항상 with 사용 (자동 close)
with open("/var/log/app.log", "r") as f:
    lines = f.readlines()           # 전체를 리스트로
    # 또는 메모리 효율적 방법:
    # for line in f:
    #     process(line)

# 파일 쓰기
results = ["server1: OK", "server2: FAIL", "server3: OK"]
with open("health_report.txt", "w") as f:
    for line in results:
        f.write(line + "\n")

# 로그 파일에서 ERROR만 추출
def extract_errors(log_path):
    errors = []
    with open(log_path, "r") as f:
        for line in f:
            if "ERROR" in line:
                errors.append(line.strip())
    return errors
```

### 6. 정규표현식 — re 모듈

```python
import re

# IP 주소 추출
log = "Connection from 192.168.1.100 to 10.0.0.1 failed"
ips = re.findall(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', log)
# ['192.168.1.100', '10.0.0.1']

# 로그 타임스탬프 파싱
log_line = "2024-01-15T10:23:45.123Z ERROR ServiceUnavailable"
match = re.match(r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})', log_line)
if match:
    date, time = match.group(1), match.group(2)

# 패턴 치환 — 민감정보 마스킹
config = "password=S3cretP@ss db_host=prod-db.internal"
masked = re.sub(r'password=\S+', 'password=****', config)
# "password=**** db_host=prod-db.internal"

# Named Group — 구조화된 파싱
pattern = r'(?P<date>\d{4}-\d{2}-\d{2}) (?P<level>ERROR|WARN|INFO) (?P<msg>.*)'
line = "2024-01-15 ERROR Connection refused"
m = re.match(pattern, line)
if m:
    print(m.group("level"))  # "ERROR"
    print(m.groupdict())     # {'date': '2024-01-15', 'level': 'ERROR', 'msg': 'Connection refused'}
```

**자주 쓰는 정규표현식 패턴:**

| 패턴 | 설명 | 예시 |
|------|------|------|
| `\d+` | 숫자 1개 이상 | "200", "404" |
| `\S+` | 공백 아닌 문자 1개 이상 | 단어, URL |
| `.*?` | 최소 매칭 (non-greedy) | 중간 내용 추출 |
| `^`, `$` | 줄의 시작/끝 | 줄 단위 매칭 |
| `(?P<name>...)` | Named Group | 구조화 파싱 |

---

## 실전 예시

### 예제 1: 로그 파일 분석 — 시간대별 에러 집계

```python
from collections import defaultdict
import re

def count_errors_by_hour(log_lines):
    """
    로그 라인에서 시간대별 ERROR 발생 횟수를 집계한다.
    입력: ["2024-01-15 10:23:45 ERROR msg1", "2024-01-15 10:55:12 ERROR msg2", ...]
    출력: {"10": 2, "14": 1, ...}
    """
    hourly = defaultdict(int)
    for line in log_lines:
        if "ERROR" in line:
            match = re.match(r'\d{4}-\d{2}-\d{2} (\d{2}):', line)
            if match:
                hour = match.group(1)
                hourly[hour] += 1
    return dict(sorted(hourly.items()))

# 테스트
logs = [
    "2024-01-15 10:23:45 ERROR Connection timeout",
    "2024-01-15 10:55:12 ERROR Disk full",
    "2024-01-15 11:00:00 INFO Service started",
    "2024-01-15 14:30:00 ERROR OOM killed",
    "2024-01-15 14:31:00 WARN High memory",
]
print(count_errors_by_hour(logs))
# {'10': 2, '14': 1}
```

### 예제 2: 서버 목록에서 중복 제거 및 정렬

```python
def normalize_servers(raw_list):
    """
    서버 목록을 정규화: 소문자 변환, 공백 제거, 중복 제거, 정렬
    """
    seen = set()
    result = []
    for s in raw_list:
        normalized = s.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return sorted(result)

servers = ["Web-01 ", " web-01", "DB-01", "cache-01", "db-01", "", "Web-02"]
print(normalize_servers(servers))
# ['cache-01', 'db-01', 'web-01', 'web-02']
```

### 예제 3: 설정 파일 파서

```python
def parse_env_file(filepath):
    """
    .env 파일을 파싱하여 dict로 반환한다.
    빈 줄과 # 주석은 무시한다.
    """
    config = {}
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip().strip('"').strip("'")
    return config

# .env 내용 예시:
# DB_HOST=prod-db.internal
# DB_PORT=5432
# SECRET_KEY="my-secret-value"
# # 이것은 주석
```

---

## 면접 Q&A / 연습 문제

### Q1. list와 dict에서 `in` 연산자의 시간복잡도 차이는?

**A:** `list`의 `in`은 **O(n)** — 순차 탐색으로 처음부터 끝까지 확인한다. `dict`의 `in`은 **O(1) 평균** — 해시 테이블 기반이므로 키 존재 여부를 상수 시간에 확인한다. 대량 데이터에서 존재 확인이 필요하면 `set`이나 `dict`를 사용해야 한다.

```python
# 나쁜 예: O(n) * m번 = O(n*m)
blocked_ips_list = ["10.0.1.1", "10.0.1.2", ...]  # 10만 개
for ip in incoming:
    if ip in blocked_ips_list:  # 매번 O(n)
        block(ip)

# 좋은 예: O(1) * m번 = O(m)
blocked_ips_set = set(blocked_ips_list)
for ip in incoming:
    if ip in blocked_ips_set:   # 매번 O(1)
        block(ip)
```

### Q2. `defaultdict`와 일반 `dict`의 차이를 설명하고 활용 예를 들어라.

**A:** `defaultdict`는 존재하지 않는 키에 접근할 때 **KeyError 대신 기본값을 자동 생성**한다. 팩토리 함수(`int`, `list`, `set` 등)를 생성자에 전달한다.

```python
# 일반 dict — 키 존재 확인 필요
groups = {}
for server in servers:
    region = get_region(server)
    if region not in groups:
        groups[region] = []
    groups[region].append(server)

# defaultdict — 깔끔
from collections import defaultdict
groups = defaultdict(list)
for server in servers:
    groups[get_region(server)].append(server)
```

### Q3. 다음 로그에서 status code별 횟수를 구하라 (Counter 활용).

```
GET /api/v1/users 200
POST /api/v1/auth 401
GET /api/v1/health 200
DELETE /api/v1/users/5 403
GET /api/v1/users 500
POST /api/v1/auth 200
```

**A:**

```python
from collections import Counter

log_data = """GET /api/v1/users 200
POST /api/v1/auth 401
GET /api/v1/health 200
DELETE /api/v1/users/5 403
GET /api/v1/users 500
POST /api/v1/auth 200"""

status_codes = [line.split()[-1] for line in log_data.strip().split("\n")]
counts = Counter(status_codes)
print(counts)              # Counter({'200': 3, '401': 1, '403': 1, '500': 1})
print(counts.most_common(1))  # [('200', 3)]
```

### Q4. 정규표현식으로 문자열에서 이메일 주소를 모두 추출하라.

**A:**

```python
import re

text = "Contact admin@allganize.ai or support@allganize.ai for help. CC: devops-team@internal.corp"
emails = re.findall(r'[\w.-]+@[\w.-]+\.\w+', text)
print(emails)
# ['admin@allganize.ai', 'support@allganize.ai', 'devops-team@internal.corp']
```

---

## Allganize 맥락

- **Alli 서비스 운영 스크립트**: 로그 파싱, 서버 상태 집계, 설정 파일 처리 등 Python 기초가 DevOps 일상 업무에 직결된다.
- **LLM 기반 서비스**: Allganize의 AI 제품은 Python 생태계(FastAPI, LangChain 등) 위에 구축되므로, 코드 리뷰나 디버깅 시 기초 문법 이해가 필수다.
- **Coderbyte 시험**: 2시간 제한 시험에서 자료구조 기초 문제가 Coding Challenges 초반에 출제될 가능성이 높다. `dict`, `set`, `Counter`를 반사적으로 쓸 수 있어야 한다.
- **10년차 인프라 경험 활용**: 코딩 테스트 문제를 "서버 로그 분석", "IP 필터링"처럼 **인프라 관점으로 재해석**하면 이해가 빠르다.

---

**핵심 키워드**: `list` `dict` `set` `Counter` `defaultdict` `re.findall` `with-open` `f-string` `list-comprehension` `시간복잡도`
