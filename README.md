# SynopStudio

## Arranque local

1. Gerar o certificado autoassinado (uma vez; fica em `traefik/certs/`, fora do git):

   ```bash
   sh traefik/generate-dev-cert.sh
   ```

2. Arrancar tudo:

   ```bash
   docker compose up --build

   # BD
   docker compose up -d postgres
   ```

3. Abrir https://localhost, https://media.localhost e https://auth.localhost uma vez cada e aceitar o aviso do
   certificado (Avançadas → Continuar). Sem aceitar `media.localhost`, os vídeos não tocam: o browser não mostra o
   aviso dentro de um `<video>`.

Apagar:

```bash
docker compose down -v
```

### Endereços

O Traefik é a única entrada (T4.36): HTTPS na porta 443 (TLS 1.2 no mínimo, TLS 1.3 quando o browser suporta) e a
porta 80 só redireciona para HTTPS.

| Endereço | Serviço |
| --- | --- |
| https://localhost | Frontend (Vite, com hot reload) |
| https://localhost/api | Backend (FastAPI), incluindo o WebSocket `/api/projects/{id}/progress`; documentação em https://localhost/api/docs |
| https://media.localhost | Links assinados dos vídeos e da waveform (SeaweedFS; só GET e HEAD) |
| https://auth.localhost | Páginas de entrada, registo e conta (Keycloak; só `/realms/` e `/resources/`) |
| http://localhost:8080/admin | Consola de administração do Keycloak (fora do Traefik) |

Em desenvolvimento, o `docker-compose.override.yml` (carregado automaticamente) publica também a porta de cada serviço,
só em `127.0.0.1`: Vite 5173, backend 8000, Postgres 5432, RabbitMQ 5672 e 15672 (interface), SeaweedFS 8333. É o que
os testes usam.

### Depois de mudar para HTTPS (ou de mudar `APP_PUBLIC_URL`)

- Os valores do `.env` sobrepõem-se aos do `docker-compose.yml`. Se o teu `.env` veio do `.env.example` antigo, atualiza
  `APP_PUBLIC_URL`, `SESSION_COOKIE_SECURE`, `S3_PUBLIC_ENDPOINT_URL` e `KEYCLOAK_PUBLIC_URL` (ou apaga essas linhas).
- O Keycloak só substitui `${APP_PUBLIC_URL}` no realm quando o importa pela primeira vez. Com uma base do Keycloak
  anterior, a entrada falha com "Invalid redirect uri" até o realm ser importado de novo. Isto apaga os utilizadores do
  realm `synopstudio` (`MSYS_NO_PATHCONV=1` só é preciso no Git Bash do Windows):

  ```bash
  MSYS_NO_PATHCONV=1 docker compose exec keycloak sh -c 'K=/opt/keycloak/bin/kcadm.sh; $K config credentials --server http://localhost:8080 --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" && $K delete realms/synopstudio'
  docker compose restart keycloak
  ```

  Alternativa que apaga todos os dados: `docker compose down -v`.

## VM do projeto

Sem o `docker-compose.override.yml`, só o Traefik fica exposto (80 e 443):

```bash
sh traefik/generate-dev-cert.sh IP:<ip-da-vm>
docker compose -f docker-compose.yml up -d --build
```

- Consola do Keycloak (presa a `127.0.0.1:8080` na VM): `ssh -L 8080:127.0.0.1:8080 <vm>` e abrir
  http://localhost:8080/admin.
- Os nomes `*.localhost` só funcionam na própria máquina. Para entrar de outro computador, escolher nomes que apontem
  para a VM (DNS ou ficheiro `hosts` de cada computador), pô-los no `.env` (`APP_HOST`, `MEDIA_HOST`, `AUTH_HOST`,
  `APP_PUBLIC_URL`, `S3_PUBLIC_ENDPOINT_URL`, `KEYCLOAK_PUBLIC_URL`) e gerar o certificado com eles, por exemplo
  `sh traefik/generate-dev-cert.sh DNS:pei.local DNS:media.pei.local DNS:auth.pei.local`. Depois, importar o realm de
  novo (secção acima).
- Quando a VM tiver domínio, trocar o certificado autoassinado por Let's Encrypt: acrescentar ao comando do `traefik`
  `--certificatesresolvers.le.acme.tlschallenge=true`, `--certificatesresolvers.le.acme.email=<email>` e
  `--certificatesresolvers.le.acme.storage=/letsencrypt/acme.json` (com um volume em `/letsencrypt`), e a cada router
  a label `traefik.http.routers.<nome>.tls.certresolver=le`. A porta 443 tem de estar aberta à Internet.
- A VM continua a correr os servidores de desenvolvimento (Vite, `uvicorn --reload`, pastas montadas); uma imagem de
  produção fica para outra tarefa.


## Virtual Environment

```bash
python3 -m venv .venv

source .venv/bin/activate

pip install -r requirements-dev.txt

python -m pytest -v

```


## LLM (Ollama)

A camada LLM (`backend/app/services/llm/`) fala com um servidor Ollama ou com um servidor compatível com OpenAI
(vLLM, llama.cpp, LM Studio). O fornecedor e o modelo escolhem-se só pela configuração: perfis em
`backend/app/core/llm.toml` e variáveis `LLM_*` (ver `.env.example`). Precedência: variável de ambiente > perfil >
valor por defeito em `config.py`.

| Perfil | Fornecedor | Modelo | Uso |
| --- | --- | --- | --- |
| `ollama-qwen` (por defeito) | Ollama | `qwen3:8b` | VM do projeto |
| `ollama-small` | Ollama | `qwen3:1.7b` | portáteis |
| `openai-compatible` | OpenAI-compatible | `Qwen/Qwen3-8B` | vLLM ou outro servidor próprio; precisa de `LLM_API_KEY` |

Até o serviço `ollama` entrar no `docker-compose.yml` (T4.16a), o Ollama corre no host:

1. Instalar o Ollama: https://ollama.com/download
2. Descarregar o modelo do perfil: `ollama pull qwen3:1.7b` (portátil) ou `ollama pull qwen3:8b` (VM).
3. Ligar os contentores ao Ollama do host (`docker info` mostra qual dos dois casos é o teu):
   - Docker Desktop (Linux, macOS ou Windows): `host.docker.internal` já chega ao Ollama em `127.0.0.1`; não é
     preciso mudar nada.
   - Docker Engine no Linux, sem Docker Desktop: o Ollama tem de ouvir em `0.0.0.0` (`sudo systemctl edit ollama`,
     acrescentar `Environment="OLLAMA_HOST=0.0.0.0"` na secção `[Service]` e `sudo systemctl restart ollama`) e o
     contentor precisa de `--add-host=host.docker.internal:host-gateway` (ou `extra_hosts` no compose). A porta
     11434 fica aberta na rede local: usar só em redes de confiança ou bloquear a porta na firewall.
4. Nos contentores: `LLM_PROFILE=ollama-small` e `LLM_BASE_URL=http://host.docker.internal:11434`.

Teste opcional com o modelo real (marker `llm`; nunca corre no CI). A imagem `app-backend` é a que o
`docker compose build backend` cria a partir da pasta `app`. Com Docker Engine no Linux, acrescentar
`--add-host=host.docker.internal:host-gateway`:

```bash
docker run --rm -v "$PWD/backend:/app" -w /app -e PYTHONDONTWRITEBYTECODE=1 -e TEST_LLM_PROFILE=ollama-small -e LLM_BASE_URL=http://host.docker.internal:11434 app-backend sh -c "pip install -q --root-user-action=ignore -r requirements-dev.txt && python -m pytest -q -p no:cacheprovider -m llm tests/test_llm_real.py"
```

Cada chamada ao LLM escreve uma linha INFO (prompt e versão, modelo, tentativas, segundos, tokens). Os textos dos
prompts e das respostas contêm a transcrição (dados pessoais) e só aparecem com `LLM_LOG_CONTENT=true` e o logger em
DEBUG (`LOG_LEVEL=DEBUG`); usar apenas com a aula de teste.
