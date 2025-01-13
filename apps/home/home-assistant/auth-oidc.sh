#!/usr/bin/env bash
set -e

curl="curl --silent"
jq="jq --raw-output"

oidc_issuer_url="${1:-$oidc_issuer_url}"
oidc_client_id="${2:-$oidc_client_id}"
oidc_client_secret="${3:-$oidc_client_secret}"

openid_config="$oidc_issuer_url/.well-known/openid-configuration"

main() {
  config_data="$($curl "$openid_config")"
  token_endpoint="$(echo "$config_data" | $jq '.token_endpoint')"

  res="$(
    $curl \
      "$token_endpoint" \
      --request POST \
      --header 'content-type: application/x-www-form-urlencoded' \
      --data 'client_id='"$oidc_client_id" \
      --data 'client_secret='"$oidc_client_secret" \
      --data grant_type=password \
      --data 'username='"$username" \
      --data 'password='"$password" \
      ;
  )"

  access_token="$(echo "$res" | $jq '.access_token')"
  >&2 echo "auth-oidc.sh: User authenticated"

  jwt_payload="$(echo "$access_token" | $jq --raw-input 'split(".") | .[1] | @base64d')"
  name="$(echo $jwt_payload | $jq '.name')"
  group="$(echo $jwt_payload | $jq 'if (.realm_access.roles | index("admin")) then "admin" else "users" end')"

  echo "name = $name"
  echo "group = system-${group:-users}"
  echo "local_only = false"
}

main
