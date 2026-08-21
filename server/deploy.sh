#!/bin/bash
set -e

REGION="${FC_REGION}"
FUNC_NAME="${FC_FUNCTION_NAME}"
CODE_B64="$(base64 -w0 ../dist/fc-package.zip)"
UPSTREAM="${AIHOT_UPSTREAM:-https://aihot.virxact.com}"

echo "Region:    ${REGION}"
echo "Function:  ${FUNC_NAME}"
echo "Code size: $(echo ${CODE_B64} | wc -c) bytes (base64)"

# 检查函数是否已存在
if aliyun fc get-function --region "${REGION}" --function-name "${FUNC_NAME}" > /dev/null 2>&1; then
  echo "Function exists → updating code & configuration..."

  aliyun fc update-function \
    --region "${REGION}" \
    --function-name "${FUNC_NAME}" \
    --code "{\"zipFile\": \"${CODE_B64}\"}" \
    --custom-runtime-config '{"command":["python3","/code/bootstrap.py"],"port":9000}'

  aliyun fc update-function \
    --region "${REGION}" \
    --function-name "${FUNC_NAME}" \
    --environment-variables '{
      "AIHOT_UPSTREAM": "'"${UPSTREAM}"'",
      "AIHOT_API_PREFIX": "/api/v1",
      "AIHOT_CACHE_TTL": "300",
      "AIHOT_MIN_POLL_INTERVAL": "60",
      "MENU_CACHE_TTL": "3600",
      "PORT": "9000"
    }'

  echo "Function updated successfully."
else
  echo "Function not found → creating with Custom Runtime..."

  aliyun fc create-function \
    --region "${REGION}" \
    --function-name "${FUNC_NAME}" \
    --runtime custom.debian10 \
    --handler index.main \
    --memory-size 256 \
    --timeout 60 \
    --instance-concurrency 10 \
    --code "{\"zipFile\": \"${CODE_B64}\"}" \
    --custom-runtime-config '{"command":["python3","/code/bootstrap.py"],"port":9000}' \
    --environment-variables '{
      "AIHOT_UPSTREAM": "'"${UPSTREAM}"'",
      "AIHOT_API_PREFIX": "/api/v1",
      "AIHOT_CACHE_TTL": "300",
      "AIHOT_MIN_POLL_INTERVAL": "60",
      "MENU_CACHE_TTL": "3600",
      "PORT": "9000"
    }'

  echo "Function created successfully."

  # 创建 HTTP 触发器（匿名访问，支持 GET/HEAD）
  echo "Creating HTTP trigger..."
  aliyun fc create-trigger \
    --region "${REGION}" \
    --function-name "${FUNC_NAME}" \
    --trigger-name http-trigger \
    --trigger-type http \
    --trigger-config '{"authType":"anonymous","methods":["GET","HEAD"]}'
  echo "HTTP trigger created."
fi

# 确保触发器存在（函数已存在但触发器可能缺失的兜底）
if ! aliyun fc get-trigger --region "${REGION}" --function-name "${FUNC_NAME}" --trigger-name http-trigger > /dev/null 2>&1; then
  echo "HTTP trigger missing → creating..."
  aliyun fc create-trigger \
    --region "${REGION}" \
    --function-name "${FUNC_NAME}" \
    --trigger-name http-trigger \
    --trigger-type http \
    --trigger-config '{"authType":"anonymous","methods":["GET","HEAD"]}'
  echo "HTTP trigger created."
else
  echo "HTTP trigger already exists."
fi

# 输出函数访问信息
echo ""
echo "=========================================="
echo "FC Function: ${FUNC_NAME}"
echo "Region:      ${REGION}"
echo "Trigger:     http-trigger (anonymous)"
echo "=========================================="
echo "请在 FC 控制台查看函数 URL 并配置到前端 API_BASE"
