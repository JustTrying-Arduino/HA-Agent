#!/usr/bin/with-contenv bashio
set -e

# Source bashio if available
if [ -f /usr/lib/bashio/bashio.sh ]; then
    # shellcheck source=/dev/null
    source /usr/lib/bashio/bashio.sh
fi

log_info() {
    if declare -F bashio::log.info >/dev/null 2>&1; then
        bashio::log.info "$@"
    else
        echo "[INFO] $*"
    fi
}

OPTIONS_FILE="/data/options.json"

get_option() {
    local key="$1"
    local default_value="${2:-}"

    if [ -f "${OPTIONS_FILE}" ]; then
        jq -er --arg key "${key}" '.[$key] // empty' "${OPTIONS_FILE}" 2>/dev/null || printf '%s' "${default_value}"
    else
        printf '%s' "${default_value}"
    fi
}

# ============================================================
# My Agent — Home Assistant Add-on Entrypoint
# ============================================================

WORKSPACE="/share/myagent/workspace"
APP_ROOT="/opt"

# --- Create persistent directories ---
mkdir -p "${WORKSPACE}/skills"

# --- Copy templates on first startup (no overwrite) ---
cp -n /usr/local/share/workspace/*.md "${WORKSPACE}/" 2>/dev/null || true
cp -rn /usr/local/share/workspace/skills/. "${WORKSPACE}/skills/" 2>/dev/null || true

# --- Read HA config → environment variables ---
export OPENAI_API_KEY="$(get_option 'openai_api_key')"
export OPENAI_API_BASE="$(get_option 'openai_api_base' 'https://api.openai.com/v1')"
export OPENAI_MODEL="$(get_option 'openai_model' 'gpt-4.1')"
export OPENAI_MODEL_LIGHT="$(get_option 'openai_model_light' 'gpt-4.1-mini')"
export GROQ_API_KEY="$(get_option 'groq_api_key')"
export BRAVE_API_KEY="$(get_option 'brave_api_key')"
export TELEGRAM_BOT_TOKEN="$(get_option 'telegram_bot_token')"
export TELEGRAM_ALLOWED_CHAT_IDS="$(get_option 'telegram_allowed_chat_ids')"
export SESSION_TIMEOUT_HOURS="$(get_option 'session_timeout_hours' '48')"
export MAX_SESSION_MESSAGES="$(get_option 'max_session_messages' '15')"
export LOG_LEVEL="$(get_option 'log_level' 'info')"
export HA_EXPOSE_LABEL="$(get_option 'ha_expose_label' 'agent')"
export PYTHONPATH="${APP_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

cd "${APP_ROOT}"

log_info "SUPERVISOR_TOKEN set: $([ -n "${SUPERVISOR_TOKEN:-}" ] && echo yes || echo no)"
log_info "All env var names: $(env | cut -d= -f1 | sort | tr '\n' ' ')"
log_info "Files in /run/: $(ls /run/ 2>/dev/null || echo 'empty')"
if declare -F bashio::var.token >/dev/null 2>&1; then
    log_info "bashio token set: $([ -n "$(bashio::var.token 2>/dev/null)" ] && echo yes || echo no)"
fi
log_info "Starting My Agent..."

# --- Launch the agent ---
exec python3 -m agent.main
