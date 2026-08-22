#!/bin/bash
# 批量修改所有知识库的 chunk_token_num 为 1024

API_BASE="https://ragflow.sustain-nexus.com/api/v1"
API_KEY="${RAGFLOW_API_KEY:?请设置环境变量 RAGFLOW_API_KEY}"

page=1
updated=0

while true; do
  response=$(curl -s -X GET "${API_BASE}/datasets?page=${page}&page_size=100" \
    -H "Authorization: Bearer ${API_KEY}")

  ids=$(echo "$response" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for ds in data.get('data', []):
    print(ds['id'], ds['name'], ds.get('parser_config', {}).get('chunk_token_num', 'N/A'), sep='|')
")

  [ -z "$ids" ] && break

  while IFS='|' read -r id name old_val; do
    echo "Updating: ${name} (${id}) chunk_token_num: ${old_val} -> 1024"
    curl -s -X PUT "${API_BASE}/datasets/${id}" \
      -H "Authorization: Bearer ${API_KEY}" \
      -H "Content-Type: application/json" \
      -d '{"parser_config": {"chunk_token_num": 1024}}' | python3 -c "
import sys, json
r = json.load(sys.stdin)
print('  Result:', 'OK' if r.get('code') == 0 else r.get('message', 'Unknown error'))
"
    updated=$((updated + 1))
  done <<< "$ids"

  total=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('total',0))")
  [ $((page * 100)) -ge "$total" ] && break
  page=$((page + 1))
done

echo "Done! Updated ${updated} datasets."
