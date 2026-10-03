#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "$script_dir/.." && pwd)"
credential_file="$project_dir/.env.yahoo.local"

if [[ ! -f "$credential_file" ]]; then
  echo "Arquivo local de configuração do Yahoo não encontrado." >&2
  exit 1
fi

cd "$project_dir"

# O arquivo indicado é lido pelo Pydantic dentro do processo Python. As credenciais
# não são interpoladas na linha de comando nem impressas pelo inicializador.
unset EMAIL_PROVIDER EMAIL_IMAP_USERNAME EMAIL_IMAP_APP_PASSWORD
export APP_ENV_FILE="$credential_file"

export DATABASE_URL="sqlite:////tmp/ad-balancas-services-8011/app.sqlite3"
export OUTPUT_DIR="/tmp/ad-balancas-services-8011/output"
export TEMPLATE_DOC_PATH="/tmp/ad-balancas-services-8011/doc_templates/proposta_template.docx"
export APP_HOST="127.0.0.1"
export APP_PORT="8011"
export APP_RELOAD="false"
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
export OLLAMA_MODEL="qwen3:4b-instruct-2507-q4_K_M"
export OLLAMA_CONNECT_TIMEOUT="3"
export OLLAMA_READ_TIMEOUT="90"
export OLLAMA_MAX_OUTPUT_TOKENS="180"
export ASSISTANT_TIMEZONE="America/Recife"
export EMAIL_MAX_MESSAGES="30"
export EMAIL_CACHE_RETENTION_DAYS="14"
export EMAIL_BODY_PREVIEW_CHARS="4000"
export VOICE_ENABLED="true"
export VOICE_MODEL_DIR="$project_dir/.models/assistant_voice"
export VOICE_PIPER_MODEL_PATH="$project_dir/.models/assistant_voice/pt_BR-faber-medium.onnx"
export VOICE_WHISPER_MODEL="small"
export VOICE_WHISPER_DEVICE="cpu"
export VOICE_WHISPER_COMPUTE_TYPE="int8"

if ! "$project_dir/.venv/bin/python" - <<'PY'
from app.config import get_settings

settings = get_settings()
credentials_ready = bool(
    settings.email_provider == "imap_yahoo"
    and settings.email_imap_username.strip()
    and settings.email_imap_app_password.get_secret_value().strip()
)
raise SystemExit(0 if credentials_ready else 1)
PY
then
  echo "Preencha o e-mail e a senha de aplicativo no arquivo local antes de iniciar a porta 8011." >&2
  exit 1
fi

exec "$project_dir/.venv/bin/python" run.py
