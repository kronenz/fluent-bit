# 올거나이즈 DevOps 면접 대비 기술 심화 자료

> **대상**: 올거나이즈코리아 DevOps/Platform Engineer 1차 기술 면접
> **작성 기준**: JD 요구사항 + AI/LLM 서비스 운영 맥락
> **총 분량**: 14개 챕터, 70+ 파일

---

## 학습 진행률

- [ ] CH01 HTTPS & 네트워크 기초 (8개 파일)
- [ ] CH02 Linux & OS 내부 (6개 파일)
- [ ] CH03 컨테이너 심화 (5개 파일)
- [ ] CH04 Kubernetes 아키텍처 (7개 파일)
- [ ] CH05 Kubernetes 네트워킹 (7개 파일)
- [ ] CH06 Kubernetes 스토리지 (4개 파일)
- [ ] CH07 CI/CD & GitOps (6개 파일)
- [ ] CH08 IaC & 멀티클라우드 (7개 파일)
- [ ] CH09 Observability & 장애 대응 (9개 파일)
- [ ] CH10 성능 & AI 서비스 (6개 파일)
- [ ] CH11 보안 (6개 파일)
- [ ] CH12 데이터베이스 운영 (3개 파일)
- [ ] CH13 코딩테스트 준비 (5개 파일)
- [ ] CH14 면접 전략 (8개 파일)

---

## D-7 ~ D-1 학습 플랜

| 날짜 | 오전 (1.5h) | 오후 (1.5h) | 저녁 (1h) |
|------|------------|------------|----------|
| **D-7** | CH01 네트워크 (01~04) | CH01 네트워크 (05~08) + CH02 Linux (01~02) | CH14-01 자기소개 연습 |
| **D-6** | CH02 Linux (03~06) + CH03 컨테이너 (01~02) | CH03 컨테이너 (03~05) + CH04 K8s 아키텍처 (01~03) | CH14-02 지원동기 연습 |
| **D-5** | CH04 K8s 아키텍처 (04~07) | CH05 K8s 네트워킹 (01~04) | CH14-04 Passionate 연습 |
| **D-4** | CH05 K8s 네트워킹 (05~07) + CH06 스토리지 | CH07 CI/CD + CH08 IaC (01~03) | CH13 코딩테스트 연습 (01~02) |
| **D-3** | CH08 IaC (04~07) + CH09 Observability (01~03) | CH09 Observability (04~09) | CH14-03 강점약점 연습 |
| **D-2** | CH10 성능/AI + CH11 보안 (01~03) | CH11 보안 (04~06) + CH12 DB | CH14-07 질문 준비 |
| **D-1** | 전체 Q&A 복습 (★★★ 빈출 위주) | CH13 코딩테스트 (03~05) | CH14-08 최종 체크리스트 |

---

## 반드시 소리내어 연습할 항목

1. **자기소개** (1분/3분) — CH14-01
2. **지원동기** 3가지 버전 — CH14-02
3. **"What are you passionate about?"** — CH14-04
4. **HTTPS TLS Handshake 설명** — CH01-02
5. **K8s Pod 생성 시 내부 동작 흐름 설명** — CH04-06
6. **장애 대응 시나리오 답변** — CH09-08
7. **면접관에게 할 질문** — CH14-07
8. **"경력이 파편적이지 않나요?" 대응** — CH14-03
9. **Terraform state 관리 설명** — CH08-02
10. **CI/CD 파이프라인 설계 설명** — CH07-01

---

## 핵심 면접 키워드 맵

```
올거나이즈 JD ←→ 학습 챕터 매핑

복원력(Resilience)      → CH04(K8s), CH06(Storage), CH09(Incident)
관측가능성(Observability) → CH09(전체), CH10-01(성능분석)
모니터링                 → CH09-01(Prometheus), CH09-02(Grafana), CH09-05(Datadog)
자동화                   → CH07(CI/CD), CH08(IaC)
AWS/Azure 멀티클라우드    → CH08-05(AWS), CH08-06(Azure), CH08-07(멀티클라우드)
CI/CD 파이프라인          → CH07(전체)
IaC(Terraform/Pulumi)   → CH08-01~04(Terraform)
성능 분석(latency/throughput) → CH10-01, CH10-02
보안 정책                → CH11(전체)
Kubernetes              → CH04, CH05, CH06
Docker/컨테이너          → CH03(전체)
Linux                   → CH02(전체)
HTTP/HTTPS & 네트워크    → CH01(전체)
MongoDB/Elasticsearch   → CH12-01, CH12-02
Python                  → CH13-01, CH13-03
Prometheus/Grafana/Datadog → CH09-01, CH09-02, CH09-05
ArgoCD & GitOps         → CH07-02, CH07-03
```

---

## 파일 작성 규칙

각 파일은 다음 구조를 따릅니다:

- **TL;DR**: 3줄 요약
- **면접 빈출도**: ★★★ / ★★☆ / ★☆☆
- **핵심 개념**: 이론 + ASCII 다이어그램
- **실전 예시**: 실행 가능한 명령어/코드
- **면접 Q&A**: 30초 답변 + 2분 답변 + 경험 연결 + 주의사항
- **Allganize 맥락**: JD 연결 포인트

---

## 지원자 프로필 요약

| 항목 | 내용 |
|------|------|
| 경력 | IT 인프라 10년+ |
| 강점 | 폐쇄망, 온프레미스, 시스템 전반 이해도 |
| 전환 포인트 | 순수 DevOps 경력은 짧지만 시스템 레벨 깊이가 강점 |
| 현재 | AI 데이터센터 구축 컨설팅 (엠키스코어) |
| 연봉 | 7,300만원 (인센 포함 7,500만+) |

---

*Generated for Allganize Korea DevOps Engineer Interview Preparation*
