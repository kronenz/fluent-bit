# 02. 알고리즘 패턴 — 정렬, 탐색, HashMap, Stack/Queue, 기초 그래프

> **TL;DR**
> - 코딩 테스트의 70%는 **HashMap(dict), 정렬, 투 포인터, Stack/Queue** 4가지 패턴으로 풀 수 있다.
> - Easy~Medium 문제는 "어떤 자료구조를 쓸 것인가"를 빠르게 판단하는 것이 핵심이다.
> - 각 패턴별 **솔루션 템플릿**을 암기해두면 2시간 시험에서 시간을 크게 절약할 수 있다.

> **면접 빈출도**: ★★★
> **예상 소요 시간**: 40min

---

## 핵심 개념

### 문제 유형별 자료구조 선택 가이드

```
"중복을 찾아라 / 빈도를 세라"          → dict (HashMap) / Counter
"정렬된 데이터에서 찾아라"              → Binary Search / 투 포인터
"괄호 매칭 / 최근 항목 추적"           → Stack
"순서대로 처리 / BFS"                 → Queue (deque)
"최단 경로 / 연결 관계"               → Graph (BFS/DFS)
"부분합 / 연속 구간"                  → Sliding Window / Prefix Sum
```

---

## 패턴 1: HashMap — 빈도 세기, 중복 탐지

### 템플릿

```python
from collections import defaultdict, Counter

def solve_with_hashmap(data):
    freq = defaultdict(int)  # 또는 Counter(data)
    for item in data:
        freq[item] += 1

    # 조건에 맞는 결과 추출
    return [k for k, v in freq.items() if v > 1]
```

### 실전 문제: Two Sum

```python
def two_sum(nums, target):
    """
    리스트에서 합이 target인 두 수의 인덱스를 반환한다.
    시간복잡도: O(n), 공간복잡도: O(n)
    """
    seen = {}  # 값 → 인덱스
    for i, num in enumerate(nums):
        complement = target - num
        if complement in seen:
            return [seen[complement], i]
        seen[num] = i
    return []

# 테스트
print(two_sum([2, 7, 11, 15], 9))   # [0, 1]
print(two_sum([3, 2, 4], 6))         # [1, 2]
```

### 실전 문제: 가장 빈번한 요소 K개

```python
from collections import Counter

def top_k_frequent(nums, k):
    """상위 k개 빈번 요소 반환. O(n log n)"""
    return [item for item, _ in Counter(nums).most_common(k)]

print(top_k_frequent([1,1,1,2,2,3], 2))  # [1, 2]
```

---

## 패턴 2: 정렬 + 투 포인터

### 템플릿

```python
def two_pointer_pattern(arr):
    arr.sort()
    left, right = 0, len(arr) - 1
    while left < right:
        current = arr[left] + arr[right]
        if current == target:
            # 찾았다
            return [arr[left], arr[right]]
        elif current < target:
            left += 1      # 합을 키우려면 왼쪽 전진
        else:
            right -= 1     # 합을 줄이려면 오른쪽 후퇴
    return []
```

### 실전 문제: 중복 제거된 정렬 배열

```python
def remove_duplicates(nums):
    """
    정렬된 배열에서 중복을 in-place로 제거하고 고유 원소 개수를 반환한다.
    공간복잡도: O(1)
    """
    if not nums:
        return 0
    write = 1
    for read in range(1, len(nums)):
        if nums[read] != nums[read - 1]:
            nums[write] = nums[read]
            write += 1
    return write

nums = [1, 1, 2, 2, 3]
k = remove_duplicates(nums)
print(nums[:k])  # [1, 2, 3]
```

### 실전 문제: 유효한 Anagram

```python
from collections import Counter

def is_anagram(s, t):
    """두 문자열이 애너그램인지 확인. O(n)"""
    return Counter(s) == Counter(t)

print(is_anagram("anagram", "nagaram"))  # True
print(is_anagram("rat", "car"))          # False
```

---

## 패턴 3: Stack — 괄호 매칭, 중첩 구조 처리

### 템플릿

```python
def solve_with_stack(data):
    stack = []
    for item in data:
        if is_opening(item):
            stack.append(item)
        elif is_closing(item):
            if not stack or not matches(stack[-1], item):
                return False
            stack.pop()
    return len(stack) == 0
```

### 실전 문제: 유효한 괄호

```python
def is_valid_brackets(s):
    """
    (), {}, [] 괄호 조합이 올바른지 확인한다.
    시간복잡도: O(n), 공간복잡도: O(n)
    """
    stack = []
    pairs = {")": "(", "}": "{", "]": "["}

    for char in s:
        if char in pairs.values():  # 여는 괄호
            stack.append(char)
        elif char in pairs:         # 닫는 괄호
            if not stack or stack[-1] != pairs[char]:
                return False
            stack.pop()
    return len(stack) == 0

print(is_valid_brackets("()[]{}"))    # True
print(is_valid_brackets("(]"))        # False
print(is_valid_brackets("{[()]}"))    # True
```

### 실전 문제: JSON/YAML 중괄호 깊이 계산

```python
def max_nesting_depth(s):
    """문자열에서 괄호의 최대 중첩 깊이를 반환한다."""
    max_depth = 0
    current = 0
    for char in s:
        if char == '(' or char == '{' or char == '[':
            current += 1
            max_depth = max(max_depth, current)
        elif char == ')' or char == '}' or char == ']':
            current -= 1
    return max_depth

print(max_nesting_depth('{"a": {"b": {"c": 1}}}'))  # 3
```

---

## 패턴 4: Queue (deque) — BFS, 순서 처리

### 템플릿

```python
from collections import deque

def bfs_pattern(start):
    queue = deque([start])
    visited = {start}

    while queue:
        node = queue.popleft()     # O(1) — list.pop(0)은 O(n)
        process(node)

        for neighbor in get_neighbors(node):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
```

### 실전 문제: 서버 의존성 순서 (위상 정렬 — Topological Sort)

```python
from collections import deque, defaultdict

def deploy_order(n, dependencies):
    """
    서버 배포 순서를 의존성에 따라 결정한다 (위상 정렬).
    dependencies: [(선행, 후행), ...] 예: [(db, app), (app, web)]
    """
    graph = defaultdict(list)
    in_degree = defaultdict(int)
    nodes = set()

    for pre, post in dependencies:
        graph[pre].append(post)
        in_degree[post] += 1
        nodes.add(pre)
        nodes.add(post)

    # in-degree가 0인 노드부터 시작
    queue = deque([n for n in nodes if in_degree[n] == 0])
    order = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(nodes):
        return []  # 순환 의존성 존재
    return order

deps = [("db", "app"), ("cache", "app"), ("app", "web"), ("web", "nginx")]
print(deploy_order(4, deps))
# ['db', 'cache', 'app', 'web', 'nginx'] 또는 ['cache', 'db', 'app', 'web', 'nginx']
```

---

## 패턴 5: 기초 그래프 — DFS/BFS

### 실전 문제: 네트워크 연결 컴포넌트 수

```python
def count_networks(n, connections):
    """
    n개의 서버와 연결 정보가 주어질 때 독립 네트워크(connected component) 수를 구한다.
    connections: [(0,1), (1,2), (3,4)] → 서버 0-1-2가 한 네트워크, 3-4가 한 네트워크
    """
    graph = defaultdict(list)
    for a, b in connections:
        graph[a].append(b)
        graph[b].append(a)

    visited = set()
    count = 0

    def dfs(node):
        visited.add(node)
        for neighbor in graph[node]:
            if neighbor not in visited:
                dfs(neighbor)

    for server in range(n):
        if server not in visited:
            dfs(server)
            count += 1
    return count

print(count_networks(5, [(0,1), (1,2), (3,4)]))  # 2 (네트워크: {0,1,2}, {3,4})
```

---

## 패턴 6: Sliding Window — 연속 구간 문제

### 템플릿

```python
def sliding_window(arr, k):
    """고정 크기 k의 윈도우에서 최대합을 구한다."""
    window_sum = sum(arr[:k])
    max_sum = window_sum

    for i in range(k, len(arr)):
        window_sum += arr[i] - arr[i - k]  # 오른쪽 추가, 왼쪽 제거
        max_sum = max(max_sum, window_sum)

    return max_sum
```

### 실전 문제: 연속 K분간 최대 트래픽

```python
def max_traffic_window(requests_per_min, k):
    """
    분당 요청 수 배열에서 연속 k분간 최대 트래픽 합을 구한다.
    시간복잡도: O(n)
    """
    if len(requests_per_min) < k:
        return sum(requests_per_min)

    window = sum(requests_per_min[:k])
    max_traffic = window

    for i in range(k, len(requests_per_min)):
        window += requests_per_min[i] - requests_per_min[i - k]
        max_traffic = max(max_traffic, window)

    return max_traffic

traffic = [100, 200, 150, 300, 250, 400, 100]
print(max_traffic_window(traffic, 3))  # 950 (300+250+400)
```

---

## 면접 Q&A / 연습 문제

### Q1. dict(HashMap)의 조회가 O(1)인 이유를 설명하라.

**A:** dict는 **해시 테이블(Hash Table)** 기반이다. 키를 해시 함수에 넣어 배열 인덱스를 직접 계산하므로, 순차 탐색 없이 O(1)에 접근한다. 해시 충돌(collision) 시 open addressing으로 처리하며, 최악의 경우 O(n)이지만 Python dict는 충돌률을 2/3 이하로 유지하도록 자동 리사이징하므로 평균 O(1)이 보장된다.

### Q2. Stack과 Queue의 차이를 설명하고, Python에서 각각 어떻게 구현하는가?

**A:**
- **Stack**: LIFO (Last In, First Out). `list`의 `append()`/`pop()`으로 구현. 함수 호출 스택, 괄호 매칭, Undo 기능에 활용.
- **Queue**: FIFO (First In, First Out). `collections.deque`의 `append()`/`popleft()`로 구현. BFS, 작업 대기열, 메시지 큐에 활용.

```python
# Stack
stack = []
stack.append(1); stack.append(2)
stack.pop()  # 2 (마지막 삽입 요소)

# Queue
from collections import deque
queue = deque()
queue.append(1); queue.append(2)
queue.popleft()  # 1 (처음 삽입 요소)
```

> **주의**: `list.pop(0)`은 O(n)이다. Queue에는 반드시 `deque.popleft()` O(1)을 사용한다.

### Q3. 다음 문제를 풀어라: 문자열에서 첫 번째 반복되지 않는 문자를 찾아라.

```python
def first_unique_char(s):
    """
    문자열에서 처음으로 한 번만 등장하는 문자의 인덱스를 반환한다.
    없으면 -1을 반환한다.
    """
    from collections import Counter
    count = Counter(s)
    for i, char in enumerate(s):
        if count[char] == 1:
            return i
    return -1

print(first_unique_char("aabbcdd"))  # 4 (첫 번째 'c')
print(first_unique_char("aabb"))     # -1
```

### Q4. Binary Search를 구현하고 시간복잡도를 설명하라.

**A:**

```python
def binary_search(arr, target):
    """
    정렬된 배열에서 target의 인덱스를 반환한다. 없으면 -1.
    시간복잡도: O(log n) — 매 단계마다 탐색 범위가 절반으로 줄어든다.
    """
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1

sorted_data = [1, 3, 5, 7, 9, 11, 13]
print(binary_search(sorted_data, 7))   # 3
print(binary_search(sorted_data, 4))   # -1
```

---

## Allganize 맥락

- **Coderbyte Easy~Medium**: Two Sum, Valid Brackets, Anagram 같은 문제가 가장 빈출한다. 위 6가지 패턴으로 대부분 커버된다.
- **DevOps 관점 재해석**: "서버 의존성 순서" = 위상 정렬, "네트워크 분리" = Connected Components, "트래픽 피크" = Sliding Window처럼 인프라 개념으로 치환하면 직관적이다.
- **시간 절약 전략**: 패턴을 인식하는 즉시 해당 템플릿을 베이스로 작성하면 Easy 문제 5~10분, Medium 문제 15~20분에 풀 수 있다.
- **Python 내장 활용**: `Counter`, `defaultdict`, `deque`, `sorted()`, `bisect` 모듈을 자유자재로 쓸 수 있으면 코드 라인 수가 절반으로 줄어든다.

---

**핵심 키워드**: `HashMap` `Two-Sum` `투포인터` `Stack` `Queue` `BFS` `DFS` `Binary-Search` `Sliding-Window` `위상정렬` `Counter` `deque`
