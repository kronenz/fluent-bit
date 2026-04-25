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

# Use tini so signals propagate when running test runs as Jobs
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/bin/bash"]

LABEL org.opencontainers.image.title="loadtest-tools" \
      org.opencontainers.image.description="Unified test tooling image: k6, hey, kube-burner, flog, avalanche, elasticsearch_exporter, opensearch-benchmark, kubectl" \
      org.opencontainers.image.source="https://github.com/kronenz/fluent-bit"
