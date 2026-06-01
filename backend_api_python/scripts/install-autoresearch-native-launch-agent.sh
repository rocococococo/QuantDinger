#!/usr/bin/env bash
set -euo pipefail

LABEL="${QUANTDINGER_AUTORESEARCH_LAUNCHD_LABEL:-com.quantdinger.autoresearch-native}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
START_SCRIPT="${BACKEND_DIR}/scripts/start-autoresearch-native-loopback.sh"
PLIST_DIR="${HOME}/Library/LaunchAgents"
LOG_DIR="${HOME}/.quantdinger/logs"
TOKEN_DIR="${HOME}/.quantdinger"
TOKEN_FILE="${AUTORESEARCH_NATIVE_API_TOKEN_FILE:-${TOKEN_DIR}/autoresearch-native-api-token}"
TOKEN_PARENT="$(dirname "${TOKEN_FILE}")"
PLIST_PATH="${PLIST_DIR}/${LABEL}.plist"
UID_VALUE="$(id -u)"

if [[ ! "${LABEL}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid launchd label: ${LABEL}" >&2
  exit 2
fi

NATIVE_TOKEN="${AUTORESEARCH_NATIVE_API_TOKEN:-}"
if [[ -z "${NATIVE_TOKEN}" && -f "${TOKEN_FILE}" ]]; then
  NATIVE_TOKEN="$(tr -d '\r\n' < "${TOKEN_FILE}")"
fi
if [[ -z "${NATIVE_TOKEN}" ]]; then
  NATIVE_TOKEN="$(uuidgen | tr '[:upper:]' '[:lower:]')"
fi

xml_escape() {
  local value="$1"
  value="${value//&/&amp;}"
  value="${value//</&lt;}"
  value="${value//>/&gt;}"
  value="${value//\"/&quot;}"
  value="${value//\'/&apos;}"
  printf '%s' "${value}"
}

ESC_HOME="$(xml_escape "${HOME}")"
ESC_START_SCRIPT="$(xml_escape "${START_SCRIPT}")"
ESC_BACKEND_DIR="$(xml_escape "${BACKEND_DIR}")"
ESC_LOG_DIR="$(xml_escape "${LOG_DIR}")"
ESC_TOKEN_FILE="$(xml_escape "${TOKEN_FILE}")"

mkdir -p "${PLIST_DIR}" "${LOG_DIR}" "${BACKEND_DIR}/logs" "${TOKEN_DIR}" "${TOKEN_PARENT}"
(
  umask 077
  printf '%s\n' "${NATIVE_TOKEN}" > "${TOKEN_FILE}"
)
chmod 600 "${TOKEN_FILE}"

cat > "${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/bash</string>
      <string>${ESC_START_SCRIPT}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
      <key>HOME</key>
      <string>${ESC_HOME}</string>
      <key>PATH</key>
      <string>/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
      <key>AUTORESEARCH_NATIVE_API_TOKEN_FILE</key>
      <string>${ESC_TOKEN_FILE}</string>
      <key>AUTORESEARCH_NATIVE_ALLOW_LOOPBACK</key>
      <string>false</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>${ESC_BACKEND_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${ESC_LOG_DIR}/autoresearch-native.out.log</string>
    <key>StandardErrorPath</key>
    <string>${ESC_LOG_DIR}/autoresearch-native.err.log</string>
  </dict>
</plist>
PLIST

chmod 644 "${PLIST_PATH}"

launchctl bootout "gui/${UID_VALUE}/${LABEL}" >/dev/null 2>&1 || true
for _attempt in 1 2 3 4 5; do
  if ! launchctl print "gui/${UID_VALUE}/${LABEL}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
for _attempt in 1 2 3; do
  if launchctl bootstrap "gui/${UID_VALUE}" "${PLIST_PATH}"; then
    break
  fi
  if [[ "${_attempt}" == "3" ]]; then
    exit 1
  fi
  sleep 1
done
launchctl enable "gui/${UID_VALUE}/${LABEL}"
launchctl kickstart -k "gui/${UID_VALUE}/${LABEL}"

echo "${PLIST_PATH}"
echo "AUTORESEARCH_NATIVE_API_TOKEN_FILE=${TOKEN_FILE}"
