#!/bin/bash
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
mkdir -p "${WORKSPACE}/cron"

# --- Copy templates on first startup (no overwrite) ---
cp -n /usr/local/share/workspace/*.md "${WORKSPACE}/" 2>/dev/null || true
if [ -d /usr/local/share/workspace/cron ]; then
    cp -n /usr/local/share/workspace/cron/* "${WORKSPACE}/cron/" 2>/dev/null || true
fi

# --- Generate crontab from JSON files ---
> /etc/crontabs/root
for f in "${WORKSPACE}/cron/"*.json; do
    [ -f "$f" ] || continue
    schedule=$(jq -r '.schedule' "$f")
    message=$(jq -r '.message' "$f")
    escaped_message=$(printf '%s' "$message" | sed "s/'/'\\\\''/g")
    echo "${schedule} cd ${APP_ROOT} && PYTHONPATH=${APP_ROOT} python3 -m agent.cron_runner '${escaped_message}'" >> /etc/crontabs/root
done

# Start crond if crontab is non-empty
if [ -s /etc/crontabs/root ]; then
    crond -b -l 8
    log_info "Cron daemon started"
fi

# --- Read HA config → environment variables ---
export OPENAI_API_KEY="$(get_option 'openai_api_key')"
export OPENAI_API_BASE="$(get_option 'openai_api_base' 'https://api.openai.com/v1')"
export OPENAI_MODEL="$(get_option 'openai_model' 'gpt-4.1')"
export GROQ_API_KEY="$(get_option 'groq_api_key')"
export BRAVE_API_KEY="$(get_option 'brave_api_key')"
export TELEGRAM_BOT_TOKEN="$(get_option 'telegram_bot_token')"
export TELEGRAM_ALLOWED_CHAT_IDS="$(get_option 'telegram_allowed_chat_ids')"
export SESSION_TIMEOUT_HOURS="$(get_option 'session_timeout_hours' '48')"
export MAX_SESSION_MESSAGES="$(get_option 'max_session_messages' '15')"
export LOG_LEVEL="$(get_option 'log_level' 'info')"
export PYTHONPATH="${APP_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

cd "${APP_ROOT}"

log_info "Starting My Agent..."

# --- Launch the agent ---
exec python3 -m agent.main
