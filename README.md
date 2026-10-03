# Sistema de Mensagens Distribuído com Docker

Avaliação G1 – Computação em Nuvem (Prof. Fábio Castro)

Três containers da mesma aplicação Python/Flask trocam mensagens entre si e as
gravam num **volume Docker compartilhado**. Toda mensagem recebida por um
container é replicada para os outros dois.

## Arquitetura

```
              host:5001          host:5002          host:5003
                  │                  │                  │
           ┌──────▼─────┐     ┌──────▼─────┐     ┌──────▼─────┐
           │    app1    │◄───►│    app2    │◄───►│    app3    │
           │  :5000     │◄───────────────────────►  :5000     │
           └──────┬─────┘     └──────┬─────┘     └──────┬─────┘
                  │    rede bridge "rede-mensagens"     │
                  └──────────────────┼──────────────────┘
                                     ▼
                  volume "mensagens-compartilhadas" (/data)
                   ├── app1.log
                   ├── app2.log
                   └── app3.log
```

* **Rede**: bridge personalizada `rede-mensagens`; os containers se acham pelo
  nome do serviço (`app1`, `app2`, `app3`) via DNS interno do Docker.
* **Volume**: `mensagens-compartilhadas`, montado em `/data` nos três containers.
  Cada container escreve **apenas no próprio arquivo** (`<instância>.log`, formato
  JSON Lines), o que evita conflito de escrita concorrente entre containers.

## Estrutura de arquivos

```
/avaliacao/
├── app/
│   ├── app.py            # Código principal (Flask: envio, replicação e verificação)
│   ├── requirements.txt  # Dependências (Flask, requests, gunicorn) com versão fixa
│   ├── Dockerfile        # Dockerfile da aplicação
│   └── .dockerignore     # Exclui arquivos desnecessários do contexto de build
├── docker-compose.yml    # Sobe app1, app2, app3 + rede + volume
├── test.sh               # Script de teste ponta a ponta
└── README.md             # Instruções
```

## Endpoints

| Método | Rota         | Descrição |
|--------|--------------|-----------|
| POST   | `/send`      | Recebe `{"message": "..."}`, grava no log local e envia cópia aos outros dois containers. Retorna `201` se todos receberam ou `207` se algum par falhou (o resultado por par vem em `replication`). `400` para JSON inválido. |
| GET    | `/messages`  | Retorna todas as mensagens gravadas no log desta instância. |
| POST   | `/replicate` | Uso interno entre containers: grava a cópia recebida sem replicar de novo (evita loop infinito). Ids repetidos são ignorados. |
| GET    | `/verify`    | Compara os ids das mensagens locais com as de cada par e informa se a replicação está correta (`replicado_corretamente`). |
| GET    | `/health`    | Usado pelo `HEALTHCHECK` do Docker. |

Cada mensagem gravada tem: `id` (UUID), `message`, `origin` (container que a
recebeu do cliente) e `timestamp` (UTC).

## Como executar

```bash
docker compose up -d --build
docker compose ps
```

### Exemplo de funcionamento

```bash
# envia para o app1
curl -X POST -H "Content-Type: application/json" -d '{"message":"hello"}' http://localhost:5001/send

# lê no app2 (a mensagem foi replicada)
curl http://localhost:5002/messages

# confere a replicação a partir de qualquer instância
curl http://localhost:5003/verify

# vê os arquivos de log no volume compartilhado
docker exec app1 ls -l /data
docker exec app1 cat /data/app2.log
```

Teste automatizado: `bash test.sh`

### Encerrar

```bash
docker compose down        # mantém as mensagens no volume
docker compose down -v     # remove também o volume
```

## Boas práticas de Docker aplicadas

* Imagem base enxuta (`python:3.12-slim`) e só as dependências necessárias, com versões fixas.
* `requirements.txt` copiado antes do código, para aproveitar o cache de camadas.
* `pip` sem cache e variáveis `PYTHONDONTWRITEBYTECODE`/`PYTHONUNBUFFERED` (logs aparecem na hora em `docker compose logs`).
* Execução com usuário sem privilégios (`appuser`), não como root.
* `HEALTHCHECK` na imagem e `restart: unless-stopped` no compose.
* Servidor de produção (`gunicorn`) no lugar do servidor de desenvolvimento do Flask.
* Configuração por variáveis de ambiente (`INSTANCE_NAME`, `PEERS`, `DATA_DIR`), assim a mesma imagem serve às três instâncias.
* Bloco comum no compose com âncora YAML (`x-app`), sem repetir configuração.
* `.dockerignore` para manter o contexto de build pequeno.

## Tolerância a falhas

Se um par estiver fora do ar, a mensagem continua sendo gravada localmente e no
outro par; o `/send` responde `207` dizendo qual par falhou, e o `/verify`
passa a mostrar `replicado_corretamente: false` com os ids que faltam.
