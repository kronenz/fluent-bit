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

echo -e "${GREEN}=== Applying Pipeline CRDs ===${NC}"

# Step 1: Lua scripts ConfigMap (FIRST)
echo -e "${YELLOW}Step 1: Applying Lua scripts ConfigMap...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/pipeline/lua-scripts-configmap.yaml" \
  "/tmp/lua-scripts-configmap.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl apply -f /tmp/lua-scripts-configmap.yaml"
echo -e "${GREEN}✓ Lua scripts ConfigMap applied${NC}"

# Step 2: ClusterFluentBitConfig (SECOND - hub)
echo -e "${YELLOW}Step 2: Applying ClusterFluentBitConfig (hub)...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/pipeline/cluster-fluentbit-config.yaml" \
  "/tmp/cluster-fluentbit-config.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl apply -f /tmp/cluster-fluentbit-config.yaml"
echo -e "${GREEN}✓ ClusterFluentBitConfig applied${NC}"

# Step 3: ClusterMultilineParser
echo -e "${YELLOW}Step 3: Applying ClusterMultilineParser...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/pipeline/cluster-multiline-parser.yaml" \
  "/tmp/cluster-multiline-parser.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl apply -f /tmp/cluster-multiline-parser.yaml"
echo -e "${GREEN}✓ ClusterMultilineParser applied${NC}"

# Step 4: ClusterInput
echo -e "${YELLOW}Step 4: Applying ClusterInput...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/pipeline/cluster-input-hostpath.yaml" \
  "/tmp/cluster-input-hostpath.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl apply -f /tmp/cluster-input-hostpath.yaml"
echo -e "${GREEN}✓ ClusterInput applied${NC}"

# Step 5: ClusterFilter
echo -e "${YELLOW}Step 5: Applying ClusterFilter...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/pipeline/cluster-filter-modify.yaml" \
  "/tmp/cluster-filter-modify.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl apply -f /tmp/cluster-filter-modify.yaml"
echo -e "${GREEN}✓ ClusterFilter applied${NC}"

# Step 6: ClusterOutput
echo -e "${YELLOW}Step 6: Applying ClusterOutput...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/pipeline/cluster-output-opensearch.yaml" \
  "/tmp/cluster-output-opensearch.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl apply -f /tmp/cluster-output-opensearch.yaml"
echo -e "${GREEN}✓ ClusterOutput applied${NC}"

# Verify
echo -e "${YELLOW}Verifying CRDs...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl get clusterfluentbitconfig,clusterinput,clusterfilter,clusteroutput,clustermultilineparser"

echo -e "${YELLOW}Checking labels...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl get clusterinput,clusterfilter,clusteroutput,clustermultilineparser --show-labels"

echo -e "${GREEN}=== Pipeline CRDs applied successfully ===${NC}"
