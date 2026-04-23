# 03. 인프라 스크립팅 — 로그 파싱, JSON/YAML, API 호출, 헬스체크

> **TL;DR**
> - DevOps 코딩 테스트의 Open-ended 파트에서는 **실제 운영 스크립트**에 가까운 문제가 출제된다.
> - 로그 파싱(정규표현식+dict), JSON/YAML 처리(`json`/`yaml` 모듈), REST API 호출(`requests`)이 3대 핵심이다.
> - 10년차 인프라 경험자는 이 영역에서 **실무 디테일**(에러 핸들링, timeout, retry)을 보여주면 강한 인상을 줄 수 있다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 35min

---

## 핵심 개념

### DevOps 스크립팅에서 자주 쓰는 Python 모듈

```python
import json          # JSON 파싱/생성
import yaml          # YAML 파싱/생성 (PyYAML)
import re            # 정규표현식
import requests      # HTTP 요청
import subprocess    # 시스템 명령 실행
import os            # 환경변수, 파일 경로
import sys           # CLI 인자
import logging       # 로그 출력
from pathlib import Path  # 경로 처리 (os.path보다 현대적)
from datetime import datetime  # 시간 처리
```

---

## 실전 예시

### 예제 1: 구조화된 로그 파서

```python
import re
from collections import defaultdict
from datetime import datetime

def parse_nginx_log(log_path):
    """
    Nginx access log를 파싱하여 통계를 반환한다.

    로그 형식 예시:
    10.0.1.100 - - [15/Jan/2024:10:23:45 +0900] "GET /api/v1/chat HTTP/1.1" 200 1234
    """
    pattern = re.compile(
        r'(?P<ip>\S+) \S+ \S+ '
        r'\[(?P<time>[^\]]+)\] '
        r'"(?P<method>\S+) (?P<path>\S+) \S+" '
        r'(?P<status>\d+) (?P<size>\d+)'
    )

    stats = {
        "total_requests": 0,
        "status_codes": defaultdict(int),
        "top_paths": defaultdict(int),
        "error_ips": defaultdict(int),
        "total_bytes": 0,
    }

    with open(log_path, "r") as f:
        for line in f:
            match = pattern.match(line)
            if not match:
                continue

            data = match.groupdict()
            stats["total_requests"] += 1
            stats["status_codes"][data["status"]] += 1
            stats["top_paths"][data["path"]] += 1
            stats["total_bytes"] += int(data["size"])

            if data["status"].startswith(("4", "5")):
                stats["error_ips"][data["ip"]] += 1

    return stats

def print_report(stats):
    """파싱 결과를 리포트 형태로 출력한다."""
    print(f"총 요청 수: {stats['total_requests']}")
    print(f"총 전송량: {stats['total_bytes'] / 1024 / 1024:.2f} MB")
    print("\n--- Status Code 분포 ---")
    for code, count in sorted(stats["status_codes"].items()):
        print(f"  {code}: {count}")
    print("\n--- Top 5 경로 ---")
    sorted_paths = sorted(stats["top_paths"].items(), key=lambda x: -x[1])[:5]
    for path, count in sorted_paths:
        print(f"  {path}: {count}")
    print("\n--- 에러 발생 IP (4xx/5xx) ---")
    for ip, count in sorted(stats["error_ips"].items(), key=lambda x: -x[1])[:5]:
        print(f"  {ip}: {count}건")
```

### 예제 2: JSON/YAML 설정 변환기

```python
import json
import yaml
from pathlib import Path

def json_to_yaml(json_path, yaml_path):
    """JSON 설정 파일을 YAML로 변환한다."""
    with open(json_path, "r") as f:
        data = json.load(f)

    with open(yaml_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    print(f"변환 완료: {json_path} → {yaml_path}")

def yaml_to_json(yaml_path, json_path):
    """YAML 설정 파일을 JSON으로 변환한다."""
    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)  # safe_load 필수! (보안)

    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"변환 완료: {yaml_path} → {json_path}")

def merge_yaml_configs(*yaml_paths):
    """여러 YAML 파일을 병합한다. 뒤의 파일이 우선한다."""
    merged = {}
    for path in yaml_paths:
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
            merged = deep_merge(merged, data)
    return merged

def deep_merge(base, override):
    """딕셔너리를 재귀적으로 병합한다."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

# 사용 예시
# base.yaml:    {app: {port: 8080, debug: true}}
# prod.yaml:    {app: {debug: false, replicas: 3}}
# 결과:         {app: {port: 8080, debug: false, replicas: 3}}
```

### 예제 3: REST API 헬스체크 스크립트

```python
import requests
import json
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

def check_endpoint(name, url, timeout=5):
    """단일 엔드포인트의 상태를 확인한다."""
    try:
        start = datetime.now()
        resp = requests.get(url, timeout=timeout)
        elapsed_ms = (datetime.now() - start).total_seconds() * 1000

        return {
            "name": name,
            "url": url,
            "status": "healthy" if resp.status_code == 200 else "unhealthy",
            "status_code": resp.status_code,
            "response_time_ms": round(elapsed_ms, 1),
        }
    except requests.exceptions.Timeout:
        return {"name": name, "url": url, "status": "timeout", "status_code": None, "response_time_ms": None}
    except requests.exceptions.ConnectionError:
        return {"name": name, "url": url, "status": "unreachable", "status_code": None, "response_time_ms": None}
    except Exception as e:
        return {"name": name, "url": url, "status": f"error: {str(e)}", "status_code": None, "response_time_ms": None}

def health_check_all(services, max_workers=5):
    """
    여러 서비스를 병렬로 헬스체크한다.
    services: [{"name": "api", "url": "http://..."}, ...]
    """
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(check_endpoint, svc["name"], svc["url"]): svc
            for svc in services
        }
        for future in as_completed(futures):
            results.append(future.result())

    return results

def print_health_report(results):
    """헬스체크 결과를 테이블 형태로 출력한다."""
    print(f"\n{'Service':<20} {'Status':<15} {'Code':<6} {'Response(ms)':<12}")
    print("-" * 55)
    for r in sorted(results, key=lambda x: x["name"]):
        code = str(r["status_code"] or "N/A")
        time = f"{r['response_time_ms']}" if r["response_time_ms"] else "N/A"
        print(f"{r['name']:<20} {r['status']:<15} {code:<6} {time:<12}")

    unhealthy = [r for r in results if r["status"] != "healthy"]
    if unhealthy:
        print(f"\n[ALERT] {len(unhealthy)}개 서비스 이상 감지!")
        sys.exit(1)
    else:
        print(f"\n[OK] 전체 {len(results)}개 서비스 정상")

# 사용 예시
if __name__ == "__main__":
    services = [
        {"name": "alli-api", "url": "http://localhost:8080/health"},
        {"name": "alli-web", "url": "http://localhost:3000/health"},
        {"name": "postgres", "url": "http://localhost:5432"},
        {"name": "redis", "url": "http://localhost:6379"},
    ]
    results = health_check_all(services)
    print_health_report(results)
```

### 예제 4: 시스템 리소스 모니터링 스크립트

```python
import subprocess
import json
import re
from datetime import datetime

def get_disk_usage():
    """df 명령으로 디스크 사용량을 파싱한다."""
    result = subprocess.run(
        ["df", "-h", "--output=target,pcent,size,avail"],
        capture_output=True, text=True
    )
    disks = []
    for line in result.stdout.strip().split("\n")[1:]:  # 헤더 스킵
        parts = line.split()
        if len(parts) >= 4:
            usage_pct = int(parts[1].rstrip("%"))
            disks.append({
                "mount": parts[0],
                "usage_percent": usage_pct,
                "total": parts[2],
                "available": parts[3],
                "alert": usage_pct > 80
            })
    return disks

def get_top_processes(n=5):
    """CPU 사용률 상위 N개 프로세스를 반환한다."""
    result = subprocess.run(
        ["ps", "aux", "--sort=-%cpu"],
        capture_output=True, text=True
    )
    processes = []
    for line in result.stdout.strip().split("\n")[1:n+1]:
        parts = line.split(None, 10)  # 최대 11개 필드
        if len(parts) >= 11:
            processes.append({
                "user": parts[0],
                "pid": parts[1],
                "cpu": float(parts[2]),
                "mem": float(parts[3]),
                "command": parts[10][:60]
            })
    return processes

def system_report():
    """시스템 상태 리포트를 JSON으로 출력한다."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "disks": get_disk_usage(),
        "top_processes": get_top_processes(),
    }

    # 알림이 필요한 디스크 확인
    alerts = [d for d in report["disks"] if d.get("alert")]
    if alerts:
        print("[WARN] 디스크 사용량 80% 초과:")
        for d in alerts:
            print(f"  {d['mount']}: {d['usage_percent']}%")

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return report
```

### 예제 5: 간단한 Retry 데코레이터

```python
import time
import functools
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def retry(max_attempts=3, delay=1, backoff=2, exceptions=(Exception,)):
    """
    실패 시 자동 재시도하는 데코레이터.
    delay: 초기 대기 시간(초)
    backoff: 대기 시간 배수 (지수 백오프)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts:
                        logger.error(f"[{func.__name__}] 최종 실패 (시도 {attempt}/{max_attempts}): {e}")
                        raise
                    logger.warning(
                        f"[{func.__name__}] 시도 {attempt}/{max_attempts} 실패: {e}. "
                        f"{current_delay}초 후 재시도..."
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff
        return wrapper
    return decorator

# 사용 예시
@retry(max_attempts=3, delay=1, backoff=2, exceptions=(requests.exceptions.RequestException,))
def call_api(url):
    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    return resp.json()
```

---

## 면접 Q&A / 연습 문제

### Q1. `yaml.load()` vs `yaml.safe_load()`의 차이와 보안 이슈를 설명하라.

**A:** `yaml.load()`는 YAML 내의 **임의의 Python 객체를 역직렬화**할 수 있어, 악의적 YAML 파일이 코드 실행(Remote Code Execution)을 일으킬 수 있다. `yaml.safe_load()`는 기본 데이터 타입(str, int, list, dict 등)만 파싱하여 안전하다.

```yaml
# 위험한 YAML (yaml.load로 로드 시 코드 실행됨)
exploit: !!python/object/apply:os.system
  args: ["rm -rf /"]
```

> **실무 규칙**: 항상 `yaml.safe_load()`를 사용한다. `yaml.load()`를 써야 하는 경우는 극히 드물다.

### Q2. `subprocess.run()`과 `os.system()`의 차이를 설명하라.

**A:**

| 항목 | `subprocess.run()` | `os.system()` |
|------|-------------------|---------------|
| 반환값 | `CompletedProcess` 객체 (stdout, stderr, returncode) | exit code (int) |
| stdout 캡처 | `capture_output=True`로 가능 | 불가 (터미널에만 출력) |
| 보안 | 리스트로 인자 전달 → shell injection 방지 | 문자열 → shell injection 취약 |
| 권장 여부 | **권장** | 비권장 (레거시) |

```python
# 나쁜 예 — shell injection 가능
user_input = "test; rm -rf /"
os.system(f"echo {user_input}")

# 좋은 예 — 인자가 분리되어 injection 불가
subprocess.run(["echo", user_input], capture_output=True, text=True)
```

### Q3. 아래 JSON 데이터에서 status가 "unhealthy"인 서비스 이름만 추출하라.

```json
{
  "services": [
    {"name": "api", "status": "healthy", "port": 8080},
    {"name": "db", "status": "unhealthy", "port": 5432},
    {"name": "cache", "status": "healthy", "port": 6379},
    {"name": "worker", "status": "unhealthy", "port": 9090}
  ]
}
```

**A:**

```python
import json

data = json.loads('''{
  "services": [
    {"name": "api", "status": "healthy", "port": 8080},
    {"name": "db", "status": "unhealthy", "port": 5432},
    {"name": "cache", "status": "healthy", "port": 6379},
    {"name": "worker", "status": "unhealthy", "port": 9090}
  ]
}''')

unhealthy = [svc["name"] for svc in data["services"] if svc["status"] == "unhealthy"]
print(unhealthy)  # ['db', 'worker']
```

### Q4. `requests` 라이브러리에서 timeout과 retry를 어떻게 처리하는가?

**A:** `timeout` 파라미터로 연결/읽기 타임아웃을 설정하고, `requests.adapters.HTTPAdapter`와 `urllib3.util.Retry`로 자동 재시도를 구성한다.

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,           # 1초, 2초, 4초 대기
    status_forcelist=[500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

# timeout=(connect_timeout, read_timeout) 초 단위
resp = session.get("https://api.example.com/health", timeout=(3, 10))
```

---

## Allganize 맥락

- **Alli 서비스 모니터링**: 헬스체크 스크립트, 로그 파싱, API 상태 확인은 Allganize DevOps 팀의 일상 업무다. 코딩 테스트에서 이런 스크립트를 작성할 수 있으면 실무 역량을 직접 어필할 수 있다.
- **K8s + Python 조합**: `kubectl` 출력을 `subprocess`로 캡처하고 JSON 파싱하여 자동화하는 패턴은 DevOps에서 매우 흔하다.
- **Open-ended 파트**: Coderbyte의 Open-ended 문제에서 "서버 모니터링 스크립트를 작성하라" 같은 실무형 문제가 출제될 가능성이 높다.
- **에러 핸들링 차별화**: try/except, timeout, retry를 자연스럽게 넣는 것이 주니어와 시니어를 구분하는 포인트다. 10년차 경험을 보여줄 수 있는 영역이다.

---

**핵심 키워드**: `로그파싱` `regex` `json.load` `yaml.safe_load` `requests` `subprocess.run` `retry` `healthcheck` `ThreadPoolExecutor` `pathlib`
