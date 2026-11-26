# SynopStudio

Arranque local:

```bash
docker compose up --build

# BD
docker compose up -d postgres
```

Apagar:

```bash
docker compose down -v
```


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
3. Aceitar ligações dos contentores com `OLLAMA_HOST=0.0.0.0`. No Linux com systemd: `sudo systemctl edit ollama`,
   acrescentar `Environment="OLLAMA_HOST=0.0.0.0"` na secção `[Service]` e `sudo systemctl restart ollama`.
   A porta 11434 fica aberta na rede local: usar só em redes de confiança ou bloquear a porta na firewall.
4. Nos contentores: `LLM_PROFILE=ollama-small` e `LLM_BASE_URL=http://host.docker.internal:11434`. No Linux este
   nome precisa de `--add-host=host.docker.internal:host-gateway` (ou `extra_hosts` no compose).

Teste opcional com o modelo real (marker `llm`; nunca corre no CI). A imagem `app-backend` é a que o
`docker compose build backend` cria a partir da pasta `app`:

```bash
docker run --rm --add-host=host.docker.internal:host-gateway -v "$PWD/backend:/app" -w /app -e PYTHONDONTWRITEBYTECODE=1 -e TEST_LLM_PROFILE=ollama-small -e LLM_BASE_URL=http://host.docker.internal:11434 app-backend sh -c "pip install -q --root-user-action=ignore -r requirements-dev.txt && python -m pytest -q -p no:cacheprovider -m llm tests/test_llm_real.py"
```

Cada chamada ao LLM escreve uma linha INFO (prompt e versão, modelo, tentativas, segundos, tokens). Os textos dos
prompts e das respostas contêm a transcrição (dados pessoais) e só aparecem com `LLM_LOG_CONTENT=true` e o logger em
DEBUG (`LOG_LEVEL=DEBUG`); usar apenas com a aula de teste.
