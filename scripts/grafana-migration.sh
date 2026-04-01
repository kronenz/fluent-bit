#!/bin/bash
###############################################################################
# Grafana Dashboard Migration Script
# dev 클러스터 → prd 클러스터로 대시보드를 API를 통해 마이그레이션
#
# 사용법:
#   chmod +x migrate_grafana_dashboards.sh
#   ./migrate_grafana_dashboards.sh
#
# 사전 준비:
#   1. dev/prd Grafana에서 각각 API Key 생성 (Admin 권한)
#      Grafana UI → Configuration → API Keys → Add API Key
#   2. 아래 설정값을 환경에 맞게 수정
#   3. jq 설치 필요: apt install jq / yum install jq / brew install jq
###############################################################################

set -euo pipefail

# ========================= 설정 =========================
SRC_URL="http://dev-grafana.example.com"      # dev Grafana URL
SRC_API_KEY="glsa_xxxxxxxxxxxx"               # dev API Key

DST_URL="http://prd-grafana.example.com"      # prd Grafana URL
DST_API_KEY="glsa_xxxxxxxxxxxx"               # prd API Key

EXPORT_DIR="./grafana_export_$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${EXPORT_DIR}/migration.log"
# =========================================================

# 색상
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo -e "$msg" | tee -a "$LOG_FILE"
}

check_prerequisites() {
    if ! command -v jq &> /dev/null; then
        echo -e "${RED}[ERROR] jq가 설치되어 있지 않습니다. 설치 후 다시 실행하세요.${NC}"
        exit 1
    fi
    if ! command -v curl &> /dev/null; then
        echo -e "${RED}[ERROR] curl이 설치되어 있지 않습니다.${NC}"
        exit 1
    fi
}

check_connection() {
    local label=$1
    local url=$2
    local api_key=$3

    local status
    status=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${api_key}" \
        "${url}/api/org")

    if [ "$status" != "200" ]; then
        echo -e "${RED}[ERROR] ${label} Grafana 연결 실패 (HTTP ${status}): ${url}${NC}"
        exit 1
    fi
    log "${GREEN}[OK]${NC} ${label} Grafana 연결 성공: ${url}"
}

# ========================= 폴더 마이그레이션 =========================
migrate_folders() {
    log "${YELLOW}[STEP 1] 폴더 마이그레이션 시작...${NC}"

    local folders
    folders=$(curl -s -H "Authorization: Bearer ${SRC_API_KEY}" \
        "${SRC_URL}/api/folders")

    local folder_count
    folder_count=$(echo "$folders" | jq 'length')
    log "  발견된 폴더 수: ${folder_count}"

    # 폴더 UID → prd 폴더 ID 매핑 저장
    declare -g -A FOLDER_MAP
    FOLDER_MAP[""]="0"  # General 폴더

    echo "$folders" | jq -c '.[]' | while read -r folder; do
        local uid title
        uid=$(echo "$folder" | jq -r '.uid')
        title=$(echo "$folder" | jq -r '.title')

        local payload
        payload=$(jq -n --arg uid "$uid" --arg title "$title" \
            '{uid: $uid, title: $title}')

        local response http_code
        response=$(curl -s -w "\n%{http_code}" \
            -X POST \
            -H "Authorization: Bearer ${DST_API_KEY}" \
            -H "Content-Type: application/json" \
            -d "$payload" \
            "${DST_URL}/api/folders")

        http_code=$(echo "$response" | tail -1)
        local body
        body=$(echo "$response" | sed '$d')

        if [ "$http_code" = "200" ] || [ "$http_code" = "412" ]; then
            log "  ${GREEN}[OK]${NC} 폴더: ${title} (uid: ${uid})"
        else
            log "  ${YELLOW}[WARN]${NC} 폴더: ${title} - HTTP ${http_code}"
        fi
    done

    log "  폴더 마이그레이션 완료"
}

# ========================= 대시보드 마이그레이션 =========================
migrate_dashboards() {
    log "${YELLOW}[STEP 2] 대시보드 마이그레이션 시작...${NC}"

    # 모든 대시보드 검색 (페이징 처리)
    local page=1
    local per_page=100
    local all_dashboards="[]"

    while true; do
        local result
        result=$(curl -s -H "Authorization: Bearer ${SRC_API_KEY}" \
            "${SRC_URL}/api/search?type=dash-db&limit=${per_page}&page=${page}")

        local count
        count=$(echo "$result" | jq 'length')

        if [ "$count" -eq 0 ]; then
            break
        fi

        all_dashboards=$(echo "$all_dashboards $result" | jq -s 'add')
        page=$((page + 1))
    done

    local total
    total=$(echo "$all_dashboards" | jq 'length')
    log "  발견된 대시보드 수: ${total}"

    # 내보내기 디렉토리에 JSON 백업 저장
    mkdir -p "${EXPORT_DIR}/dashboards"

    local success=0
    local fail=0
    local skip=0

    echo "$all_dashboards" | jq -c '.[]' | while read -r item; do
        local uid title folder_uid folder_title
        uid=$(echo "$item" | jq -r '.uid')
        title=$(echo "$item" | jq -r '.title')
        folder_uid=$(echo "$item" | jq -r '.folderUid // empty')
        folder_title=$(echo "$item" | jq -r '.folderTitle // "General"')

        # dev에서 대시보드 상세 조회
        local dash_detail
        dash_detail=$(curl -s -H "Authorization: Bearer ${SRC_API_KEY}" \
            "${SRC_URL}/api/dashboards/uid/${uid}")

        local dash_found
        dash_found=$(echo "$dash_detail" | jq -r '.dashboard // empty')
        if [ -z "$dash_found" ]; then
            log "  ${RED}[FAIL]${NC} ${title} - 대시보드 조회 실패"
            fail=$((fail + 1))
            continue
        fi

        # JSON 백업 저장
        echo "$dash_detail" | jq '.' > "${EXPORT_DIR}/dashboards/${uid}.json"

        # prd로 import할 payload 구성
        local payload
        if [ -n "$folder_uid" ]; then
            payload=$(echo "$dash_detail" | jq \
                --arg folder_uid "$folder_uid" \
                '{
                    dashboard: .dashboard,
                    folderUid: $folder_uid,
                    overwrite: true,
                    message: "Migrated from dev"
                } | .dashboard.id = null')
        else
            payload=$(echo "$dash_detail" | jq \
                '{
                    dashboard: .dashboard,
                    folderId: 0,
                    overwrite: true,
                    message: "Migrated from dev"
                } | .dashboard.id = null')
        fi

        # prd에 import
        local response http_code
        response=$(curl -s -w "\n%{http_code}" \
            -X POST \
            -H "Authorization: Bearer ${DST_API_KEY}" \
            -H "Content-Type: application/json" \
            -d "$payload" \
            "${DST_URL}/api/dashboards/db")

        http_code=$(echo "$response" | tail -1)
        local body
        body=$(echo "$response" | sed '$d')

        if [ "$http_code" = "200" ]; then
            log "  ${GREEN}[OK]${NC} ${title} (폴더: ${folder_title})"
            success=$((success + 1))
        else
            local err_msg
            err_msg=$(echo "$body" | jq -r '.message // "unknown error"')
            log "  ${RED}[FAIL]${NC} ${title} - ${err_msg} (HTTP ${http_code})"
            fail=$((fail + 1))
        fi

        # API Rate limit 방지
        sleep 0.3
    done

    log ""
    log "========================================="
    log "  마이그레이션 결과"
    log "  전체: ${total}"
    log "  JSON 백업 위치: ${EXPORT_DIR}/dashboards/"
    log "========================================="
}

# ========================= 데이터소스 비교 =========================
compare_datasources() {
    log "${YELLOW}[STEP 3] 데이터소스 비교...${NC}"

    local src_ds dst_ds
    src_ds=$(curl -s -H "Authorization: Bearer ${SRC_API_KEY}" \
        "${SRC_URL}/api/datasources" | jq -r '.[].name' | sort)
    dst_ds=$(curl -s -H "Authorization: Bearer ${DST_API_KEY}" \
        "${DST_URL}/api/datasources" | jq -r '.[].name' | sort)

    local missing
    missing=$(comm -23 <(echo "$src_ds") <(echo "$dst_ds"))

    if [ -n "$missing" ]; then
        log "  ${YELLOW}[WARN] prd에 없는 데이터소스 (대시보드가 정상 작동하려면 추가 필요):${NC}"
        while IFS= read -r ds; do
            log "    - ${ds}"
        done <<< "$missing"
    else
        log "  ${GREEN}[OK]${NC} 모든 데이터소스가 prd에 존재합니다."
    fi
}

# ========================= 메인 =========================
main() {
    mkdir -p "$EXPORT_DIR"
    touch "$LOG_FILE"

    log "========================================="
    log "  Grafana 대시보드 마이그레이션"
    log "  SRC: ${SRC_URL}"
    log "  DST: ${DST_URL}"
    log "========================================="

    check_prerequisites
    check_connection "SRC(dev)" "$SRC_URL" "$SRC_API_KEY"
    check_connection "DST(prd)" "$DST_URL" "$DST_API_KEY"

    migrate_folders
    migrate_dashboards
    compare_datasources

    log ""
    log "${GREEN}마이그레이션 완료! 로그: ${LOG_FILE}${NC}"
    log "대시보드 JSON 백업: ${EXPORT_DIR}/dashboards/"
}

main
