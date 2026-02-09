#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Checking Prerequisites ===${NC}"

# Check Python3
if ! command -v python3 &> /dev/null; then
  echo -e "${RED}ERROR: python3 is not installed${NC}"
  echo "Install it with: sudo apt-get install python3 (Ubuntu/Debian) or brew install python3 (macOS)"
  exit 1
fi
echo -e "${GREEN}✓ python3 installed${NC}"

# Check pexpect module
if ! python3 -c "import pexpect" &> /dev/null; then
  echo -e "${RED}ERROR: Python pexpect module is not installed${NC}"
  echo "Install it with: pip3 install pexpect (or pip install pexpect)"
  exit 1
fi
echo -e "${GREEN}✓ pexpect module installed${NC}"

# Check .env exists
if [ ! -f "${SCRIPT_DIR}/.env" ]; then
  echo -e "${RED}ERROR: ${SCRIPT_DIR}/.env file not found${NC}"
  echo "Copy .env.example to .env and fill in your SSH credentials"
  exit 1
fi
echo -e "${GREEN}✓ .env file exists${NC}"

# Source .env
source "${SCRIPT_DIR}/.env"

# Test SSH connection
echo -e "${YELLOW}Testing SSH connection to ${SSH_USER}@${SSH_HOST}...${NC}"
if ! "${SCRIPT_DIR}/remote-exec.sh" "echo 'SSH connection successful'" &> /dev/null; then
  echo -e "${RED}ERROR: Cannot connect via SSH${NC}"
  exit 1
fi
echo -e "${GREEN}✓ SSH connection successful${NC}"

# Check kubectl on remote
echo -e "${YELLOW}Checking kubectl on remote...${NC}"
if ! "${SCRIPT_DIR}/remote-exec.sh" "command -v kubectl" &> /dev/null; then
  echo -e "${RED}ERROR: kubectl not found on remote host${NC}"
  exit 1
fi
echo -e "${GREEN}✓ kubectl available${NC}"

# Check helm on remote
echo -e "${YELLOW}Checking helm on remote...${NC}"
if ! "${SCRIPT_DIR}/remote-exec.sh" "command -v helm" &> /dev/null; then
  echo -e "${RED}ERROR: helm not found on remote host${NC}"
  exit 1
fi
echo -e "${GREEN}✓ helm available${NC}"

# Add helm repos
echo -e "${YELLOW}Adding helm repositories...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "helm repo add opensearch https://opensearch-project.github.io/helm-charts/ 2>/dev/null || true"
"${SCRIPT_DIR}/remote-exec.sh" "helm repo add fluent https://fluent.github.io/helm-charts 2>/dev/null || true"
echo -e "${GREEN}✓ Helm repos added${NC}"

# Update helm repos
echo -e "${YELLOW}Updating helm repositories...${NC}"
"${SCRIPT_DIR}/remote-exec.sh" "helm repo update"
echo -e "${GREEN}✓ Helm repos updated${NC}"

echo -e "${GREEN}=== All prerequisites satisfied ===${NC}"
