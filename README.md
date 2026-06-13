# AI ArgoCD Explainer (Day 24)

Reads ArgoCD application status and explains sync failures in plain English using AI.

## Features

- Parses ArgoCD application status JSON (`argocd app get <name> -o json`)
- Extracts sync status, health status, resource states, and conditions
- Identifies specific failure reasons (operation failures, unhealthy resources, out-of-sync)
- AI-powered explanations via Ollama (local) or OpenAI (fallback)
- JSON and human-readable output formats
- Supports multi-source applications

## Requirements

- Python 3.11+
- ArgoCD CLI (to export app status)
- Ollama (optional, for local AI) or OpenAI API key (optional, for remote AI)

## Quick Start

```bash
# Export ArgoCD app status
argocd app get my-app -o json > app.json

# View status
python src/main.py app.json

# Get failure reasons only
python src/main.py app.json --reasons-only

# With AI explanation
python src/main.py app.json --explain

# JSON output
python src/main.py app.json --json
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3` | Ollama model name |
| `OPENAI_API_KEY` | (none) | OpenAI API key for fallback |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name |

## Architecture

```
ai-argocd-explainer/
  src/
    argocd_parser.py    # ArgoCD status parsing + failure detection
    llm.py              # LLM client (Ollama + OpenAI fallback)
    main.py             # CLI entry point
  tests/
    test_argocd_parser.py  # Comprehensive test suite
  .github/workflows/
    ci.yml              # GitHub Actions CI
  Dockerfile
  docker-compose.yml
```

## Running Tests

```bash
python -m pytest tests/ -v
```

## Docker

```bash
# Build and run
docker compose run ai-argocd-explainer /app/status/app.json

# With AI explanation
docker compose run ai-argocd-explainer /app/status/app.json --explain
```
