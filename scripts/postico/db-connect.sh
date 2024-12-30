#!/usr/bin/env nix
#! nix shell nixpkgs#bash nixpkgs#kubectl nixpkgs#jq nixpkgs#coreutils --command bash

namespace="$PGDATABASE"
pod="$PGHOST"
connection_secret="$PGPASSWORD-app"
certificate_secret="$PGPASSWORD-ca"

# TODO: figure out how to get Postico to background the kubectl call without getting hung
# used_psql_ports="$(ps -f | grep -E 'kubectl\s+port-forward' | grep -E '(649[0-9]{2}):5432' | wc -l)"
# port="$((64920 + $used_psql_ports))"
# kubectl port-forward pod/postgres-1 -n "$namespace" "$port":5432 &> /dev/stderr &

# instead of above, we'll look for an already-config'd port-forward
port="$(ps -f | grep -E 'kubectl\s+port-forward' | grep -E "(-n|--namespace)[ =]+$namespace" | grep -E '(649[0-9]{2}):5432' | sed -nEe 's/.+\b(649[0-9]{2}):.+/\1/p')"

connection="$(
  kubectl get secret "$connection_secret" -n "$namespace" -o jsonpath='{.data}' \
    | jq '
        .
        | map_values(@base64d)
        | .host |= "127.0.0.1"
        | .port |= "'$port'"
        | { host, port, dbname, user, password }
      '
)"

# ca_content="$(
#   kubectl get secret "$certificate_secret" -n "$namespace" -o jsonpath='{.data}' \
#     | jq '
#         .
#         | map_values(@base64d)
#         | { crt: ."ca.crt", key: ."ca.key" }
#       '
# )"

crt_file=""
key_file=""
# echo "$ca_content" | jq '.crt' > "$crt_file"
# echo "$ca_content" | jq '.key' > "$key_file"

ca='{ "sslcert": "$crt_file", "sslkey": "$key_file" }'

echo "[$connection,$ca]" | jq 'add'
