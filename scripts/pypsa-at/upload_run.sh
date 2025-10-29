#!/bin/bash
# Upload PyPSA-AT run results to dashboard API
#
# Usage: ./upload_run.sh <scenario_path> [api_url] [token]
#
# Arguments:
#   scenario_path - Path to scenario folder (e.g., results/high_res/scenario)
#   api_url       - Optional: API endpoint URL (default: http://internal.aggm.at:8080/api/upload)
#   token         - Optional: Bearer token (default: from UPLOAD_TOKEN env var)
#
# Example:
#   export UPLOAD_TOKEN="your_token_here"
#   ./upload_run.sh results/v2025.01/AT_KN2040
#
#   Or with explicit token:
#   ./upload_run.sh results/high_res/scenario http://api.example.com/upload my_token

set -euo pipefail

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
SCENARIO_PATH="${1:-}"
API_URL="${2:-http://localhost:8080/api/upload}"
TOKEN="${3:-${UPLOAD_TOKEN:-}}"

# Validation
if [[ -z "$SCENARIO_PATH" ]]; then
    echo -e "${RED}Error: Scenario path is required${NC}"
    echo "Usage: $0 <scenario_path> [api_url] [token]"
    echo "Example: $0 results/high_res/scenario"
    exit 1
fi

if [[ ! -d "$SCENARIO_PATH" ]]; then
    echo -e "${RED}Error: Scenario path does not exist: $SCENARIO_PATH${NC}"
    exit 1
fi

JSON_DIR="$SCENARIO_PATH/evaluation/JSON"
if [[ ! -d "$JSON_DIR" ]]; then
    echo -e "${RED}Error: JSON directory not found: $JSON_DIR${NC}"
    exit 1
fi

if [[ -z "$TOKEN" ]]; then
    echo -e "${RED}Error: Upload token not provided${NC}"
    echo "Set UPLOAD_TOKEN environment variable or pass as third argument"
    exit 1
fi

# Extract run and scenario names from path
SCENARIO_NAME=$(basename "$SCENARIO_PATH")
RUN_NAME=$(basename "$(dirname "$SCENARIO_PATH")")

echo -e "${GREEN}=== PyPSA-AT Upload Script ===${NC}"
echo "Run: $RUN_NAME"
echo "Scenario: $SCENARIO_NAME"
echo "JSON directory: $JSON_DIR"
echo "API endpoint: $API_URL"
echo ""

# Count JSON files
JSON_COUNT=$(find "$JSON_DIR" -maxdepth 1 -name "*.json" -type f | wc -l)
echo -e "${YELLOW}Found $JSON_COUNT JSON files${NC}"

if [[ $JSON_COUNT -lt 1 ]]; then
    echo -e "${RED}Error: No JSON files found in $JSON_DIR${NC}"
    exit 1
fi

# Create temporary directory for archive
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

ARCHIVE_NAME="${RUN_NAME}_${SCENARIO_NAME}.tar.gz"
ARCHIVE_PATH="$TEMP_DIR/$ARCHIVE_NAME"

echo -e "${YELLOW}Creating archive: $ARCHIVE_NAME${NC}"

# Create tar.gz archive of all JSON files
tar -czf "$ARCHIVE_PATH" -C "$JSON_DIR" --transform 's|^|json/|' *.json

# Get archive size
ARCHIVE_SIZE=$(du -h "$ARCHIVE_PATH" | cut -f1)
echo -e "${GREEN}Archive created: $ARCHIVE_SIZE${NC}"
echo ""

# Upload to API
echo -e "${YELLOW}Uploading to $API_URL...${NC}"

HTTP_RESPONSE=$(curl -X POST "$API_URL" \
    -H "Authorization: Bearer $TOKEN" \
    -F "file=@$ARCHIVE_PATH" \
    -w "\nHTTP_STATUS:%{http_code}" \
    -s)

# Parse response
HTTP_BODY=$(echo "$HTTP_RESPONSE" | sed -e 's/HTTP_STATUS\:.*//g')
HTTP_STATUS=$(echo "$HTTP_RESPONSE" | tr -d '\n' | sed -e 's/.*HTTP_STATUS://')

echo ""
if [[ $HTTP_STATUS -ge 200 && $HTTP_STATUS -lt 300 ]]; then
    echo -e "${GREEN}✓ Upload successful (HTTP $HTTP_STATUS)${NC}"
    echo "$HTTP_BODY" | jq . 2>/dev/null || echo "$HTTP_BODY"
else
    echo -e "${RED}✗ Upload failed (HTTP $HTTP_STATUS)${NC}"
    echo "$HTTP_BODY"
    exit 1
fi

echo ""
echo -e "${GREEN}Done!${NC}"