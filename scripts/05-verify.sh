#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

PASS_COUNT=0
FAIL_COUNT=0

check_pass() {
  echo -e "${GREEN}✓ PASS: $1${NC}"
  PASS_COUNT=$((PASS_COUNT + 1))
}

check_fail() {
  echo -e "${RED}✗ FAIL: $1${NC}"
  FAIL_COUNT=$((FAIL_COUNT + 1))
}

echo -e "${GREEN}=== End-to-End Verification ===${NC}"

# Check 1: ClusterFluentBitConfig exists
echo -e "${YELLOW}[1/9] Checking ClusterFluentBitConfig...${NC}"
if "${SCRIPT_DIR}/remote-exec.sh" "kubectl get clusterfluentbitconfig fluent-bit-config" &> /dev/null; then
  check_pass "ClusterFluentBitConfig exists"
else
  check_fail "ClusterFluentBitConfig not found"
fi

# Check 2: CRD labels
echo -e "${YELLOW}[2/9] Checking CRD labels...${NC}"
LABEL_CHECK=$("${SCRIPT_DIR}/remote-exec.sh" "kubectl get clusterinput,clusterfilter,clusteroutput -l fluentbit.fluent.io/enabled=true --no-headers 2>/dev/null | wc -l" || echo "0")
# Strip whitespace/newlines from output
LABEL_CHECK=$(echo "$LABEL_CHECK" | tr -d '[:space:]')
if [ "$LABEL_CHECK" -gt 0 ] 2>/dev/null; then
  check_pass "CRD labels configured correctly ($LABEL_CHECK CRDs found)"
else
  check_fail "CRD labels missing or incorrect"
fi

# Check 3: Sample app log file exists
echo -e "${YELLOW}[3/9] Checking sample app log file...${NC}"
if "${SCRIPT_DIR}/remote-exec.sh" "kubectl exec -n sample-app deploy/log-generator -- test -f /var/log/sample-app/app.log" &> /dev/null; then
  check_pass "Sample app log file exists"
else
  check_fail "Sample app log file not found"
fi

# Check 4: Fluent Bit pod logs for errors
echo -e "${YELLOW}[4/9] Checking Fluent Bit pod logs for errors...${NC}"
FB_ERRORS=$("${SCRIPT_DIR}/remote-exec.sh" "kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit --tail=50 2>/dev/null | grep -i 'error' | grep -v -i 'password' | grep -v -F '[filter' || true")
# Strip whitespace/control chars from output
FB_ERRORS=$(echo "$FB_ERRORS" | sed '/^[[:space:]]*$/d')
if [ -z "$FB_ERRORS" ]; then
  check_pass "No errors in Fluent Bit logs"
else
  check_fail "Errors found in Fluent Bit logs"
  echo -e "${RED}${FB_ERRORS}${NC}"
fi

# Check 5: OpenSearch cluster health
echo -e "${YELLOW}[5/9] Checking OpenSearch cluster health...${NC}"
OS_HEALTH=$("${SCRIPT_DIR}/remote-exec.sh" "kubectl exec -n logging opensearch-cluster-master-0 -- curl -s http://localhost:9200/_cluster/health?pretty | grep status" || echo "")
if [[ "$OS_HEALTH" == *"green"* ]] || [[ "$OS_HEALTH" == *"yellow"* ]]; then
  check_pass "OpenSearch cluster is healthy"
else
  check_fail "OpenSearch cluster health check failed"
fi

# Check 6: OpenSearch indices exist
echo -e "${YELLOW}[6/9] Checking OpenSearch indices...${NC}"
sleep 10  # Wait for indices to be created
INDICES=$("${SCRIPT_DIR}/remote-exec.sh" "kubectl exec -n logging opensearch-cluster-master-0 -- curl -s 'http://localhost:9200/_cat/indices/app-logs-*?h=index'" || echo "")
if [ -n "$INDICES" ]; then
  check_pass "OpenSearch indices created"
  echo -e "${GREEN}Indices: ${INDICES}${NC}"
else
  check_fail "No OpenSearch indices found"
fi

# Check 7: OpenSearch data exists
echo -e "${YELLOW}[7/9] Checking OpenSearch data...${NC}"
DOC_COUNT=$("${SCRIPT_DIR}/remote-exec.sh" "kubectl exec -n logging opensearch-cluster-master-0 -- curl -s 'http://localhost:9200/app-logs-*/_search?size=0' | grep '\"total\"' | head -1" || echo "")
if [[ "$DOC_COUNT" == *"\"value\""* ]] && [[ ! "$DOC_COUNT" == *"\"value\":0"* ]]; then
  check_pass "OpenSearch contains log data"
  echo -e "${GREEN}${DOC_COUNT}${NC}"
else
  check_fail "No log data in OpenSearch"
fi

# Check 8: Namespace field in documents
echo -e "${YELLOW}[8/9] Checking namespace field in documents...${NC}"
SAMPLE_DOC=$("${SCRIPT_DIR}/remote-exec.sh" "kubectl exec -n logging opensearch-cluster-master-0 -- curl -s 'http://localhost:9200/app-logs-*/_search?size=1&pretty' | grep '\"namespace\"'" || echo "")
if [[ "$SAMPLE_DOC" == *"\"namespace\""* ]]; then
  check_pass "Namespace field exists in documents"
  echo -e "${GREEN}${SAMPLE_DOC}${NC}"
else
  check_fail "Namespace field not found in documents"
fi

# Check 9: Verify sample-app namespace value
echo -e "${YELLOW}[9/9] Checking sample-app namespace value...${NC}"
if [[ "$SAMPLE_DOC" == *"sample-app"* ]]; then
  check_pass "sample-app namespace correctly indexed"
else
  check_fail "sample-app namespace not found in data"
fi

# Summary
echo ""
echo -e "${GREEN}=== Verification Summary ===${NC}"
echo -e "PASSED: ${GREEN}${PASS_COUNT}${NC}"
echo -e "FAILED: ${RED}${FAIL_COUNT}${NC}"

if [ $FAIL_COUNT -eq 0 ]; then
  echo -e "${GREEN}All checks passed!${NC}"
  exit 0
else
  echo -e "${RED}Some checks failed. Please review the output above.${NC}"
  exit 1
fi
