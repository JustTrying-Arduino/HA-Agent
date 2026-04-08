#!/usr/bin/with-bashio

# ============================================================
# My Agent — Home Assistant Add-on Entrypoint
# ============================================================

WORKSPACE="/share/myagent/workspace"

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
    echo "${schedule} python3 /opt/agent/cron_runner.py '${escaped_message}'" >> /etc/crontabs/root
done

# Start crond if crontab is non-empty
if [ -s /etc/crontabs/root ]; then
    crond -b -l 8
    bashio::log.info "Cron daemon started"
fi

# --- Read HA config → environment variables ---
export OPENAI_API_KEY="$(bashio::config 'openai_api_key')"
export OPENAI_API_BASE="$(bashio::config 'openai_api_base')"
export OPENAI_MODEL="$(bashio::config 'openai_model')"
export GROQ_API_KEY="$(bashio::config 'groq_api_key')"
export BRAVE_API_KEY="$(bashio::config 'brave_api_key')"
export TELEGRAM_BOT_TOKEN="$(bashio::config 'telegram_bot_token')"
export TELEGRAM_ALLOWED_CHAT_IDS="$(bashio::config 'telegram_allowed_chat_ids')"
export SESSION_TIMEOUT_HOURS="$(bashio::config 'session_timeout_hours')"
export MAX_SESSION_MESSAGES="$(bashio::config 'max_session_messages')"
export LOG_LEVEL="$(bashio::config 'log_level')"

bashio::log.info "Starting My Agent..."

# --- Launch the agent ---
exec python3 /opt/agent/main.py
