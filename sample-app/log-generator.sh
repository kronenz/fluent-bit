#!/bin/sh

# POSIX-compliant log generator for Log4j2 JSON format
# Works with busybox sh

LOG_PATH="${LOG_PATH:-/var/log/sample-app}"
NAMESPACE="${NAMESPACE:-default}"
BURST_MODE="${BURST_MODE:-false}"
BURST_RATE="${BURST_RATE:-100}"

mkdir -p "$LOG_PATH"
LOG_FILE="$LOG_PATH/app.log"

# Generate random hex string
random_hex() {
  len="$1"
  od -An -N$(expr $len / 2) -tx1 /dev/urandom | tr -d ' \n' | head -c "$len"
}

# Generate epoch milliseconds
epoch_millis() {
  printf '%s000' "$(date +%s)"
}

# Log levels array simulation
get_random_level() {
  rand=$(od -An -N1 -tu1 /dev/urandom | tr -d ' ')
  mod=$(expr $rand % 100)

  if [ $mod -lt 60 ]; then
    echo "INFO"
  elif [ $mod -lt 80 ]; then
    echo "DEBUG"
  elif [ $mod -lt 95 ]; then
    echo "WARN"
  else
    echo "ERROR"
  fi
}

# Get random message
get_random_message() {
  rand=$(od -An -N1 -tu1 /dev/urandom | tr -d ' ')
  mod=$(expr $rand % 10)

  case $mod in
    0) echo "Processing request for user authentication" ;;
    1) echo "Database query completed in 45ms" ;;
    2) echo "Cache miss for key: session_12345" ;;
    3) echo "HTTP request completed: GET /api/users status=200" ;;
    4) echo "Message published to queue: order.created" ;;
    5) echo "Service health check passed" ;;
    6) echo "Starting background job: data-sync" ;;
    7) echo "Configuration reloaded successfully" ;;
    8) echo "Connection pool size: 10/50" ;;
    9) echo "Request rate: 150 req/s" ;;
  esac
}

# Generate stacktrace
generate_stacktrace() {
  cat <<'STACKTRACE'
java.lang.NullPointerException: Cannot invoke method on null object
	at com.example.service.UserService.processRequest(UserService.java:123)
	at com.example.controller.UserController.handleRequest(UserController.java:45)
	at com.example.filter.AuthFilter.doFilter(AuthFilter.java:78)
	at org.springframework.web.servlet.DispatcherServlet.doDispatch(DispatcherServlet.java:1234)
	at javax.servlet.http.HttpServlet.service(HttpServlet.java:750)
Caused by: java.lang.IllegalStateException: Invalid state
	at com.example.service.ValidationService.validate(ValidationService.java:89)
	at com.example.service.UserService.processRequest(UserService.java:120)
	... 4 more
STACKTRACE
}

# Generate single log entry
generate_log() {
  timestamp=$(epoch_millis)
  thread="Thread-$(od -An -N1 -tu1 /dev/urandom | tr -d ' ' | awk '{print $1 % 20}')"
  level=$(get_random_level)
  logger_name="com.example.service.$(printf 'Service%d' $(od -An -N1 -tu1 /dev/urandom | tr -d ' ' | awk '{print $1 % 5}'))"
  message=$(get_random_message)
  trace_id=$(random_hex 16)
  span_id=$(random_hex 16)

  # 10% chance of multiline stacktrace
  rand=$(od -An -N1 -tu1 /dev/urandom | tr -d ' ')
  if [ $(expr $rand % 100) -lt 10 ]; then
    stacktrace=$(generate_stacktrace | sed 's/"/\\"/g' | sed ':a;N;$!ba;s/\n/\\n/g')
    message="$message\\n$stacktrace"
    level="ERROR"
  fi

  # Escape message for JSON
  message=$(printf '%s' "$message" | sed 's/"/\\"/g')

  # Output Log4j2 JSON format
  printf '{"timeMillis":%s,"thread":"%s","level":"%s","loggerName":"%s","message":"%s","contextMap":{"traceId":"%s","spanId":"%s","namespace":"%s"}}\n' \
    "$timestamp" "$thread" "$level" "$logger_name" "$message" "$trace_id" "$span_id" "$NAMESPACE" >> "$LOG_FILE"
}

# Main loop
if [ "$BURST_MODE" = "true" ]; then
  echo "Starting log generator in BURST mode: $BURST_RATE logs/sec"
  while true; do
    i=0
    while [ $i -lt "$BURST_RATE" ]; do
      generate_log
      i=$(expr $i + 1)
    done
    sleep 1
  done
else
  echo "Starting log generator in NORMAL mode"
  while true; do
    generate_log
    sleep $(od -An -N1 -tu1 /dev/urandom | awk '{print 1 + ($1 % 2)}')
  done
fi
