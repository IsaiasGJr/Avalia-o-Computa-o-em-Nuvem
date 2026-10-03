#!/usr/bin/env bash
# Teste ponta a ponta: envia uma mensagem para cada instância e confere a replicação.
set -e

for port in 5001 5002 5003; do
  echo ">> POST /send em localhost:$port"
  curl -s -X POST -H "Content-Type: application/json" \
       -d "{\"message\":\"teste via porta $port\"}" "http://localhost:$port/send"
  echo
done

sleep 1
for port in 5001 5002 5003; do
  echo ">> GET /messages em localhost:$port"
  curl -s "http://localhost:$port/messages"
  echo
done

echo ">> GET /verify em localhost:5001"
curl -s http://localhost:5001/verify
echo
