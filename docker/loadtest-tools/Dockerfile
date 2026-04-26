# Unified load-testing tools image.
# Single image bundles every CLI used by deploy/load-testing/04-test-jobs/* and
# every load-target binary used by 03-load-generators/*. Built once, pushed to
# the air-gap Nexus, and referenced by all manifests with a different command.
#
# Versions pinned to early-2025 stable releases.

# ---- Source images (multi-stage COPY) ----
ARG K6_VERSION=0.55.0
ARG KB_VERSION=v1.13.0
ARG FLOG_VERSION=0.4.3
ARG AVALANCHE_VERSION=v0.7.0
ARG ESEXP_VERSION=v1.8.0
ARG KUBECTL_VERSION=1.32.0
ARG OSB_VERSION=1.7.0
# Pinned commit on the OpenSearch benchmark workloads default branch (main).
# Updated 2026-04 — bump as needed and rebuild.
ARG OSB_WORKLOADS_REF=main

FROM grafana/k6:${K6_VERSION} AS k6
FROM quay.io/kube-burner/kube-burner:${KB_VERSION} AS kube-burner
FROM mingrammer/flog:${FLOG_VERSION} AS flog
FROM quay.io/prometheuscommunity/avalanche:${AVALANCHE_VERSION} AS avalanche
FROM quay.io/prometheuscommunity/elasticsearch-exporter:${ESEXP_VERSION} AS esexp

# ---- Builder for hey (rakyll/hey has no official image with a stable tag) ----
FROM golang:1.24-alpine AS hey-builder
RUN apk add --no-cache git ca-certificates \
 && go install github.com/rakyll/hey@latest

# ---- Final ----
FROM python:3.11-slim AS final
ARG KUBECTL_VERSION
ARG OSB_VERSION

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        curl wget jq bash ca-certificates git tini \
        procps net-tools iputils-ping dnsutils \
 && rm -rf /var/lib/apt/lists/*

# kubectl
RUN curl -fsSL "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
        -o /usr/local/bin/kubectl \
 && chmod +x /usr/local/bin/kubectl

# opensearch-benchmark (Python)
RUN pip install --no-cache-dir "opensearch-benchmark==${OSB_VERSION}"

# opensearch-benchmark workload definitions (so air-gap doesn't need to clone
# https://github.com/opensearch-project/opensearch-benchmark-workloads at run
# time). Corpus data (.json.bz2 from benchmarks.opensearch.org) is too large
# to bake in full; only the test-mode 1k subsets are baked. Full corpus →
# PVC mount at /opt/osb-data 또는 OSB download 명령 (인터넷 환경).
ARG OSB_WORKLOADS_REF
# Pre-stage workloads at /opt/osb-workloads. We use --workload-path in the
# Job manifest so opensearch-benchmark never tries to git-fetch the default
# repo. .git is removed because OSB attempts `git checkout` on it even with
# --offline, which fails on shallow clones.
RUN git clone --depth 1 -b ${OSB_WORKLOADS_REF} \
        https://github.com/opensearch-project/opensearch-benchmark-workloads.git \
        /opt/osb-workloads \
 && rm -rf /opt/osb-workloads/.git
ENV OSB_WORKLOADS_PATH=/opt/osb-workloads

# Pre-download test-mode corpus (1k docs subset) for selected workloads.
# Without these, `opensearch-benchmark execute-test --test-mode` fails with:
#   SystemSetupError: Cannot find [.../documents-X-1k.json.bz2]
# OSB looks for corpus at ~/.benchmark/benchmarks/data/<workload>/
# Source: https://dbyiw3u3rf9yr.cloudfront.net/corpora/<workload>/<file>
# (URL extracted from each workload's workload.json `base-url` field)
# Total size baked: < 5 MB (test-mode files are tiny).
# 운영 부하 측정 (--test-mode 미사용) 시에는 PVC 에 full corpus 사전 적재 필요.
RUN set -ex \
 && apt-get update && apt-get install -y --no-install-recommends bzip2 \
 && rm -rf /var/lib/apt/lists/*

# OSB offline-mode patch:
#   loader.py 의 prepare_document_set 가 .offset 파일이 로컬에 있어도
#   원격 다운로드를 시도하고, offline 시 SystemSetupError (DataError 가
#   아님!) 를 raise → 외부 except 가 잡지 못 함.
#   → 패치: 로컬에 .offset 있으면 다운로드 건너뛰고, 다운로드 실패 시
#     SystemSetupError 도 catch (create_file_offset_table 가 이어서
#     로컬 생성).
RUN python3 - << 'PYEOF'
import re, sys
path = '/usr/local/lib/python3.11/site-packages/osbenchmark/workload/loader.py'
src = open(path).read()

old = """    if document_set.support_file_offset_table:
            if not document_set.source_url:
                try:
                    self.downloader.download(document_set.base_url, None, doc_path + '.offset', None)
                except exceptions.DataError as e:
                    if isinstance(e.cause, urllib.error.HTTPError) and (e.cause.code == 403 or e.cause.code == 404):
                        self.logger.info("Pre-generated offset file not found, will generate from corpus data")
            self.create_file_offset_table(doc_path, document_set.number_of_lines)"""

new = """    if document_set.support_file_offset_table:
            if not document_set.source_url:
                offset_path = doc_path + '.offset'
                if not os.path.exists(offset_path):
                    try:
                        self.downloader.download(document_set.base_url, None, offset_path, None)
                    except (exceptions.DataError, exceptions.SystemSetupError) as e:
                        self.logger.info(f"Pre-generated offset file not available: {e}")
            self.create_file_offset_table(doc_path, document_set.number_of_lines)"""

if old not in src:
    print("WARNING: target block not found verbatim; trying single-line replace", file=sys.stderr)
    # Fallback: just widen except clause
    src2 = src.replace(
        "except exceptions.DataError as e:\n                    if isinstance(e.cause, urllib.error.HTTPError)",
        "except (exceptions.DataError, exceptions.SystemSetupError) as e:\n                    if not hasattr(e, 'cause') or isinstance(getattr(e, 'cause', None), urllib.error.HTTPError)"
    )
    if src2 == src:
        sys.exit("OSB offline patch FAILED: neither pattern matched")
    src = src2
else:
    src = src.replace(old, new)

open(path, 'w').write(src)
print("OSB offline patch applied")
PYEOF

# 모든 OSB workload 의 test-mode 코퍼스를 사전 다운로드.
# Pre-download ALL workloads' test-mode corpora — for offline operation of
# any workload (`OSB_WORKLOAD=...` 변경만으로 다른 시나리오 실행 가능).
# Source: <workload>/files.txt 에 list 된 파일 중 "-1k." 또는 "1k.json" 패턴.
# Base URL: workload.json 의 corpora.base-url (없으면 cloudfront default).
# Total size: < 100 MB (1k subset across ~14 workloads).
RUN set -ex \
 && DEFAULT_BASE=https://dbyiw3u3rf9yr.cloudfront.net/corpora \
 && DATA=/root/.benchmark/benchmarks/data \
 && for w in /opt/osb-workloads/*/; do \
      WORKLOAD=$(basename "$w"); \
      FILES_TXT="$w/files.txt"; \
      [ -f "$FILES_TXT" ] || continue; \
      mkdir -p "${DATA}/${WORKLOAD}"; \
      # base-url 추출 (workload.json 의 corpora.base-url; 없으면 default)
      BASE=$(grep -oE '"base-url"\s*:\s*"[^"]+"' "$w/workload.json" 2>/dev/null \
              | head -1 | sed -E 's/.*"([^"]+)"$/\1/'); \
      [ -z "$BASE" ] && BASE="${DEFAULT_BASE}/${WORKLOAD}"; \
      echo "=== ${WORKLOAD} ($BASE) ==="; \
      # files.txt 에서 1k pattern 만 추출
      grep -E '(-1k|1k)\.json' "$FILES_TXT" 2>/dev/null | while read FILE; do \
          [ -z "$FILE" ] && continue; \
          JSON=${FILE%.bz2}; \
          if curl -fsSL --max-time 60 "${BASE}/${FILE}" -o "${DATA}/${WORKLOAD}/${FILE}"; then \
            bunzip2 -k -f "${DATA}/${WORKLOAD}/${FILE}" 2>/dev/null \
              && touch "${DATA}/${WORKLOAD}/${JSON}.offset" \
              && echo "  ✓ ${FILE}"; \
          else \
            echo "  ✗ ${FILE} (skip)"; \
            rm -f "${DATA}/${WORKLOAD}/${FILE}"; \
          fi; \
      done; \
    done \
 && echo "=== 다운로드 완료 ===" \
 && du -sh /root/.benchmark/benchmarks/data/ \
 && for d in /root/.benchmark/benchmarks/data/*/; do \
      W=$(basename "$d"); \
      N=$(ls "$d" 2>/dev/null | wc -l); \
      echo "  $W: $N files"; \
    done

# Binaries from upstream images
COPY --from=k6        /usr/bin/k6                                 /usr/local/bin/k6
COPY --from=kube-burner /bin/kube-burner                          /usr/local/bin/kube-burner
COPY --from=flog      /bin/flog                                   /usr/local/bin/flog
COPY --from=avalanche /bin/avalanche                              /usr/local/bin/avalanche
COPY --from=esexp     /bin/elasticsearch_exporter                 /usr/local/bin/elasticsearch_exporter
COPY --from=hey-builder /go/bin/hey                               /usr/local/bin/hey

# Sanity: make sure each binary runs at build time
RUN k6 version \
 && kube-burner version \
 && flog --version \
 && avalanche --version \
 && elasticsearch_exporter --version 2>&1 | head -1 \
 && hey --help 2>&1 | head -1 || true \
 && kubectl version --client \
 && opensearch-benchmark --version

WORKDIR /work

# Disable phone-home / telemetry for offline operation (k6 sends a usage
# report to Grafana endpoint after each test by default; in air-gap it fails
# silently but adds latency). Other tools have no telemetry.
ENV K6_NO_USAGE_REPORT=true

# Use tini so signals propagate when running test runs as Jobs
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/bin/bash"]

LABEL org.opencontainers.image.title="loadtest-tools" \
      org.opencontainers.image.description="Unified test tooling image: k6, hey, kube-burner, flog, avalanche, elasticsearch_exporter, opensearch-benchmark, kubectl" \
      org.opencontainers.image.source="https://github.com/kronenz/fluent-bit"
