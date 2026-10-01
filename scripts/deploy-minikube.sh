#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
namespace="${NAMESPACE:-flight-status}"
app_image="${APP_IMAGE:-flight-status:local}"
app_local_port="${APP_LOCAL_PORT:-8081}"

for command in kubectl terraform curl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$command" >&2
    exit 1
  fi
done

kubectl cluster-info >/dev/null
terraform -chdir="$project_root/terraform" init
terraform -chdir="$project_root/terraform" apply -var="app_image=$app_image" "$@"

if ! kubectl -n "$namespace" get secret flight-api >/dev/null 2>&1; then
  printf 'Kubernetes Secret flight-api is missing in namespace %s. Create it as documented in README.md, then rerun this script.\n' "$namespace" >&2
  exit 1
fi

kubectl -n "$namespace" rollout restart deployment/flight-status
kubectl -n "$namespace" rollout status deployment/flight-status --timeout=180s
kubectl -n "$namespace" rollout status deployment/grafana --timeout=180s

forward_pids=()
cleanup() {
  for pid in "${forward_pids[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in "${forward_pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

kubectl -n "$namespace" port-forward service/flight-status "$app_local_port:80" --address 127.0.0.1 &
forward_pids+=("$!")
if curl -fsS --max-time 2 http://127.0.0.1:3000/api/health | grep -Eq '"database"[[:space:]]*:[[:space:]]*"ok"'; then
  printf 'Reusing the Grafana port-forward already listening on port 3000.\n'
else
  kubectl -n "$namespace" port-forward service/grafana 3000:3000 --address 127.0.0.1 &
  forward_pids+=("$!")
fi

printf 'App:     http://localhost:%s\n' "$app_local_port"
printf 'Grafana: http://localhost:3000\n'
printf 'Keep this script running while using the local links. Press Ctrl-C to stop both port-forwards.\n'
wait -n "${forward_pids[@]}"