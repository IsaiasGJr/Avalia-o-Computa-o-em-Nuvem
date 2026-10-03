"""
Sistema de mensagens distribuído - Computação em Nuvem (G1)

Cada instância (app1, app2, app3) expõe uma API REST na porta 5000:
  POST /send       -> recebe {"message": "..."}, grava no seu log e replica para os pares
  POST /replicate  -> uso interno: recebe uma cópia vinda de outro container
  GET  /messages   -> lista as mensagens gravadas no log desta instância
  GET  /verify     -> confere se todas as mensagens estão replicadas nos pares
  GET  /health     -> verificação de saúde (usada pelo HEALTHCHECK do Docker)

Persistência: cada container mantém o próprio arquivo <INSTANCE_NAME>.log
(JSON Lines) dentro do volume compartilhado montado em DATA_DIR.
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, request

INSTANCE_NAME = os.getenv("INSTANCE_NAME", "app")
DATA_DIR = os.getenv("DATA_DIR", "/data")
# Lista de pares no formato "host:porta,host:porta" (nomes de serviço do compose)
PEERS = [p.strip() for p in os.getenv("PEERS", "").split(",") if p.strip()]
REPLICATION_TIMEOUT = float(os.getenv("REPLICATION_TIMEOUT", "3"))

LOG_FILE = os.path.join(DATA_DIR, f"{INSTANCE_NAME}.log")
_file_lock = threading.Lock()

logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [{INSTANCE_NAME}] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)


# ---------------------------------------------------------------- persistência
def _read_messages():
    if not os.path.exists(LOG_FILE):
        return []
    with _file_lock, open(LOG_FILE, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _store_message(msg):
    """Grava a mensagem no log desta instância (ignora ids duplicados)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with _file_lock:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, encoding="utf-8") as f:
                if any(json.loads(l)["id"] == msg["id"] for l in f if l.strip()):
                    return False
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return True


# ----------------------------------------------------------------- replicação
def _replicate(msg):
    """Envia uma cópia da mensagem para cada par e devolve o status por par."""
    results = {}
    for peer in PEERS:
        url = f"http://{peer}/replicate"
        try:
            r = requests.post(url, json=msg, timeout=REPLICATION_TIMEOUT)
            r.raise_for_status()
            results[peer] = "ok"
        except requests.RequestException as exc:
            log.warning("Falha ao replicar %s para %s: %s", msg["id"], peer, exc)
            results[peer] = f"erro: {exc.__class__.__name__}"
    return results


# ------------------------------------------------------------------ endpoints
@app.post("/send")
def send():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not str(data.get("message", "")).strip():
        return jsonify(error='JSON inválido. Formato esperado: {"message": "texto"}'), 400

    msg = {
        "id": str(uuid.uuid4()),
        "message": str(data["message"]),
        "origin": INSTANCE_NAME,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _store_message(msg)
    log.info("Mensagem %s recebida: %r", msg["id"], msg["message"])

    replication = _replicate(msg)
    status = 201 if all(v == "ok" for v in replication.values()) else 207
    return jsonify(stored=msg, replication=replication), status


@app.post("/replicate")
def replicate():
    msg = request.get_json(silent=True)
    if not isinstance(msg, dict) or not {"id", "message", "origin"} <= msg.keys():
        return jsonify(error="payload de replicação inválido"), 400
    created = _store_message(msg)
    log.info("Réplica %s recebida de %s (nova=%s)", msg["id"], msg["origin"], created)
    return jsonify(status="replicated" if created else "duplicate", id=msg["id"]), 200


@app.get("/messages")
def messages():
    msgs = _read_messages()
    return jsonify(instance=INSTANCE_NAME, count=len(msgs), messages=msgs)


@app.get("/verify")
def verify():
    """Compara os ids desta instância com os de cada par."""
    local_ids = {m["id"] for m in _read_messages()}
    report = {}
    for peer in PEERS:
        try:
            r = requests.get(f"http://{peer}/messages", timeout=REPLICATION_TIMEOUT)
            r.raise_for_status()
            peer_ids = {m["id"] for m in r.json()["messages"]}
            report[peer] = {
                "faltando_no_par": sorted(local_ids - peer_ids),
                "faltando_aqui": sorted(peer_ids - local_ids),
                "sincronizado": local_ids == peer_ids,
            }
        except requests.RequestException as exc:
            report[peer] = {"erro": exc.__class__.__name__, "sincronizado": False}
    all_ok = all(v["sincronizado"] for v in report.values())
    return jsonify(instance=INSTANCE_NAME, total_local=len(local_ids),
                   replicado_corretamente=all_ok, pares=report)


@app.get("/health")
def health():
    return jsonify(status="ok", instance=INSTANCE_NAME)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
