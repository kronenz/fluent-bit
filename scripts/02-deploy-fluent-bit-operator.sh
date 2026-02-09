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

echo -e "${GREEN}=== Deploying Fluent Bit Operator ===${NC}"

# Deploy Fluent Bit Operator
echo -e "${YELLOW}Deploying Fluent Bit Operator...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/infra/fluent-bit-operator/values.yaml" \
  "/tmp/fluent-bit-operator-values.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "helm install fluent-bit-operator fluent/fluent-operator --version 3.2.0 -n logging -f /tmp/fluent-bit-operator-values.yaml"
echo -e "${GREEN}✓ Fluent Bit Operator installed${NC}"

# Wait for operator pod
echo -e "${YELLOW}Waiting for operator pod to be ready...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=fluent-operator -n logging --timeout=300s"
echo -e "${GREEN}✓ Operator pod ready${NC}"

# Wait for fluent-bit daemonset pods
echo -e "${YELLOW}Waiting for Fluent Bit DaemonSet pods to be ready...${NC}"
sleep 10  # Give DaemonSet time to create pods
"${SCRIPT_DIR}/remote-exec.sh" "kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=fluent-bit -n logging --timeout=300s"
echo -e "${GREEN}✓ Fluent Bit DaemonSet pods ready${NC}"

# Verify
echo -e "${YELLOW}Verifying deployment...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl get daemonset -n logging"

echo -e "${GREEN}=== Fluent Bit Operator deployment complete ===${NC}"
