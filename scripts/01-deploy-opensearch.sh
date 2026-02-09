#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ ! -f "${SCRIPT_DIR}/.env" ]; then
  echo -e "${RED}ERROR: ${SCRIPT_DIR}/.env file not found${NC}"
  exit 1
fi

source "${SCRIPT_DIR}/.env"
export SSH_HOST SSH_USER SSH_PASSWORD

echo -e "${GREEN}=== Deploying OpenSearch ===${NC}"

# Create namespace
echo -e "${YELLOW}Creating logging namespace...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/infra/namespace.yaml" \
  "/tmp/namespace.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl apply -f /tmp/namespace.yaml"
echo -e "${GREEN}✓ Namespace created${NC}"

# Deploy OpenSearch
echo -e "${YELLOW}Deploying OpenSearch...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/infra/opensearch/values.yaml" \
  "/tmp/opensearch-values.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "helm install opensearch opensearch/opensearch --version 2.28.0 -n logging -f /tmp/opensearch-values.yaml"
echo -e "${GREEN}✓ OpenSearch installed${NC}"

# Deploy OpenSearch Dashboards
echo -e "${YELLOW}Deploying OpenSearch Dashboards...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/infra/opensearch-dashboards/values.yaml" \
  "/tmp/dashboards-values.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "helm install dashboards opensearch/opensearch-dashboards --version 2.24.0 -n logging -f /tmp/dashboards-values.yaml"
echo -e "${GREEN}✓ OpenSearch Dashboards installed${NC}"

# Wait for pods
echo -e "${YELLOW}Waiting for OpenSearch pods to be ready (timeout 300s)...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=opensearch -n logging --timeout=300s"
echo -e "${GREEN}✓ OpenSearch pods ready${NC}"

# Verify health
echo -e "${YELLOW}Verifying OpenSearch health...${NC}"
sleep 5  # Give a moment for service to stabilize
"${SCRIPT_DIR}/remote-exec.sh" "kubectl exec -n logging opensearch-cluster-master-0 -- curl -s http://localhost:9200/_cluster/health?pretty" || echo -e "${YELLOW}Health check skipped (may need more time)${NC}"

echo -e "${GREEN}=== OpenSearch deployment complete ===${NC}"
