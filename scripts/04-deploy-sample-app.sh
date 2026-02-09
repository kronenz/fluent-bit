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

echo -e "${GREEN}=== Deploying Sample App ===${NC}"

# Ensure namespace exists
echo -e "${YELLOW}Ensuring sample-app namespace exists...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/infra/namespace.yaml" \
  "/tmp/namespace.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl apply -f /tmp/namespace.yaml"
echo -e "${GREEN}✓ Namespace ready${NC}"

# Apply ConfigMap
echo -e "${YELLOW}Applying ConfigMap...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/sample-app/configmap.yaml" \
  "/tmp/sample-app-configmap.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl apply -f /tmp/sample-app-configmap.yaml"
echo -e "${GREEN}✓ ConfigMap applied${NC}"

# Apply Deployment
echo -e "${YELLOW}Applying Deployment...${NC}"
"${SCRIPT_DIR}/scp-helper.py" \
  "${PROJECT_ROOT}/sample-app/deployment.yaml" \
  "/tmp/sample-app-deployment.yaml"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl apply -f /tmp/sample-app-deployment.yaml"
echo -e "${GREEN}✓ Deployment applied${NC}"

# Wait for pod
echo -e "${YELLOW}Waiting for pod to be ready...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "kubectl wait --for=condition=ready pod -l app=log-generator -n sample-app --timeout=300s"
echo -e "${GREEN}✓ Pod ready${NC}"

# Verify logs
echo -e "${YELLOW}Verifying logs are being written...${NC}"
sleep 5  # Give time for logs to be generated
"${SCRIPT_DIR}/remote-exec.sh" "kubectl exec -n sample-app deploy/log-generator -- tail -3 /var/log/sample-app/app.log"

echo -e "${GREEN}=== Sample app deployment complete ===${NC}"
