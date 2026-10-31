#!/usr/bin/env bash
# Teste da G1 rodando no Swarm com dois PCs.
# Uso: bash test-swarm.sh <IP_PC1> <IP_PC2>
set -e
PC1=${1:?informe o IP do PC 1}
PC2=${2:?informe o IP do PC 2}

echo ">> Enviando pelo PC 1 (app1)"
curl -s -X POST -H "Content-Type: application/json" \
     -d '{"message":"enviada pelo PC 1"}' "http://$PC1:5001/send"; echo

echo ">> Enviando pelo PC 2 (app2)"
curl -s -X POST -H "Content-Type: application/json" \
     -d '{"message":"enviada pelo PC 2"}' "http://$PC2:5002/send"; echo

sleep 1
echo ">> Lendo o app3 pelo IP do PC 1 (routing mesh)"
curl -s "http://$PC1:5003/messages"; echo

echo ">> Verificando a replicação"
curl -s "http://$PC1:5001/verify"; echo
