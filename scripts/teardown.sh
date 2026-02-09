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

echo -e "${GREEN}=== Tearing Down Environment ===${NC}"

# Delete sample-app
echo -e "${YELLOW}Deleting sample-app deployment...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl delete -f /tmp/sample-app-deployment.yaml --ignore-not-found=true" || true
echo -e "${GREEN}✓ Sample app deployment deleted${NC}"

echo -e "${YELLOW}Deleting sample-app configmap...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl delete -f /tmp/sample-app-configmap.yaml --ignore-not-found=true" || true
echo -e "${GREEN}✓ Sample app configmap deleted${NC}"

# Delete pipeline CRDs (reverse order)
echo -e "${YELLOW}Deleting ClusterOutput...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl delete -f /tmp/cluster-output-opensearch.yaml --ignore-not-found=true" || true
echo -e "${GREEN}✓ ClusterOutput deleted${NC}"

echo -e "${YELLOW}Deleting ClusterFilter...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl delete -f /tmp/cluster-filter-modify.yaml --ignore-not-found=true" || true
echo -e "${GREEN}✓ ClusterFilter deleted${NC}"

echo -e "${YELLOW}Deleting ClusterInput...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl delete -f /tmp/cluster-input-hostpath.yaml --ignore-not-found=true" || true
echo -e "${GREEN}✓ ClusterInput deleted${NC}"

echo -e "${YELLOW}Deleting ClusterMultilineParser...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl delete -f /tmp/cluster-multiline-parser.yaml --ignore-not-found=true" || true
echo -e "${GREEN}✓ ClusterMultilineParser deleted${NC}"

echo -e "${YELLOW}Deleting ClusterFluentBitConfig...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl delete -f /tmp/cluster-fluentbit-config.yaml --ignore-not-found=true" || true
echo -e "${GREEN}✓ ClusterFluentBitConfig deleted${NC}"

echo -e "${YELLOW}Deleting Lua scripts ConfigMap...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl delete -f /tmp/lua-scripts-configmap.yaml --ignore-not-found=true" || true
echo -e "${GREEN}✓ Lua scripts ConfigMap deleted${NC}"

# Uninstall helm releases
echo -e "${YELLOW}Uninstalling Fluent Bit Operator...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "helm uninstall fluent-bit-operator -n logging" || true
echo -e "${GREEN}✓ Fluent Bit Operator uninstalled${NC}"

echo -e "${YELLOW}Uninstalling OpenSearch Dashboards...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "helm uninstall dashboards -n logging" || true
echo -e "${GREEN}✓ OpenSearch Dashboards uninstalled${NC}"

echo -e "${YELLOW}Uninstalling OpenSearch...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "helm uninstall opensearch -n logging" || true
echo -e "${GREEN}✓ OpenSearch uninstalled${NC}"

# Wait for pod termination
echo -e "${YELLOW}Waiting for pods to terminate...${NC}"
sleep 10

# Delete namespaces
echo -e "${YELLOW}Deleting namespaces...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl delete namespace logging --ignore-not-found=true" || true
"${SCRIPT_DIR}/remote-exec.sh" "kubectl delete namespace sample-app --ignore-not-found=true" || true
echo -e "${GREEN}✓ Namespaces deleted${NC}"

# Clean up remote temp files
echo -e "${YELLOW}Cleaning up remote temp files...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "rm -f /tmp/namespace.yaml /tmp/opensearch-values.yaml /tmp/dashboards-values.yaml /tmp/fluent-bit-operator-values.yaml /tmp/lua-scripts-configmap.yaml /tmp/cluster-fluentbit-config.yaml /tmp/cluster-multiline-parser.yaml /tmp/cluster-input-hostpath.yaml /tmp/cluster-filter-modify.yaml /tmp/cluster-output-opensearch.yaml /tmp/sample-app-configmap.yaml /tmp/sample-app-deployment.yaml" || true
echo -e "${GREEN}✓ Temp files cleaned${NC}"

echo -e "${GREEN}=== Cleanup complete ===${NC}"
