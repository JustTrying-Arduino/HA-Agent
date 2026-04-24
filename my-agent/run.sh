#!/usr/bin/with-contenv bashio
set -e

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
    local missing_marker="__MY_AGENT_OPTION_MISSING__"
    local value

    if [ -f "${OPTIONS_FILE}" ]; then
        value="$(jq -r --arg key "${key}" --arg missing "${missing_marker}" 'if has($key) and .[$key] != null then .[$key] else $missing end' "${OPTIONS_FILE}" 2>/dev/null)"
        if [ -n "${value}" ] && [ "${value}" != "${missing_marker}" ]; then
            printf '%s' "${value}"
        else
            printf '%s' "${default_value}"
        fi
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
mkdir -p "${WORKSPACE}/chats"

# --- Copy templates on first startup (no overwrite) ---
cp -n /usr/local/share/workspace/*.md "${WORKSPACE}/" 2>/dev/null || true
cp -rn /usr/local/share/workspace/skills/. "${WORKSPACE}/skills/" 2>/dev/null || true
cp -rn /usr/local/share/workspace/chats/. "${WORKSPACE}/chats/" 2>/dev/null || true

# --- Read HA config → environment variables ---
export OPENAI_API_KEY="$(get_option 'openai_api_key')"
export OPENAI_API_BASE="$(get_option 'openai_api_base' 'https://api.openai.com/v1')"
export OPENAI_MODEL="$(get_option 'openai_model' 'gpt-4.1')"
export OPENAI_MODEL_LIGHT="$(get_option 'openai_model_light' 'gpt-4.1-mini')"
export GROQ_API_KEY="$(get_option 'groq_api_key')"
export BRAVE_API_KEY="$(get_option 'brave_api_key')"
export DEGIRO_USERNAME="$(get_option 'degiro_username')"
export DEGIRO_PASSWORD="$(get_option 'degiro_password')"
export DEGIRO_TOTP_SEED="$(get_option 'degiro_totp_seed')"
export DEGIRO_DATA_DIR="/data/degiro"
mkdir -p "${DEGIRO_DATA_DIR}"
if [ ! -f "${DEGIRO_DATA_DIR}/.key" ]; then
    head -c 32 /dev/urandom | base64 > "${DEGIRO_DATA_DIR}/.key"
    chmod 600 "${DEGIRO_DATA_DIR}/.key"
fi
export DEGIRO_KEY="$(cat "${DEGIRO_DATA_DIR}/.key")"
export TELEGRAM_BOT_TOKEN="$(get_option 'telegram_bot_token')"
export TELEGRAM_ALLOWED_CHAT_IDS="$(get_option 'telegram_allowed_chat_ids')"
export SESSION_TIMEOUT_HOURS="$(get_option 'session_timeout_hours' '48')"
export MAX_SESSION_MESSAGES="$(get_option 'max_session_messages' '15')"
export INCLUDE_RECENT_TOOL_CALLS="$(get_option 'include_recent_tool_calls' 'true')"
export LOG_LEVEL="$(get_option 'log_level' 'info')"
export HA_EXPOSE_LABEL="$(get_option 'ha_expose_label' 'agent')"
export PYTHONPATH="${APP_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

cd "${APP_ROOT}"

log_info "Starting My Agent..."

# --- Launch the agent ---
exec python3 -m agent.main
