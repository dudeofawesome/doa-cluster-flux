#!/usr/bin/env bash
set -e

# this might break in the future (which is probably good)
# https://github.com/operator-framework/operator-controller/issues/1341

version="latest/download"
if [ -n "$1" ]; then
  echo "Updating to version $1"
  version="download/$1"
else
  echo "Updating to latest"
fi

# There are some duplicate resources defined in the yaml files downloaded below
# In order to make them valid for fluxcd, we need to remove the duplicates
duplicate_filter='
  (.apiVersion == "v1" and .kind == "Namespace" and .metadata.name == "olmv1-system")
  or (.apiVersion == "cert-manager.io/v1" and .kind == "ClusterIssuer" and .metadata.name == "olmv1-ca")
  or (.apiVersion == "cert-manager.io/v1" and .kind == "Issuer" and .metadata.name == "self-sign-issuer")
  or (.apiVersion == "cert-manager.io/v1" and .kind == "Certificate" and .metadata.name == "olmv1-ca")
'

curl \
  --silent \
  --fail \
  -L https://github.com/operator-framework/catalogd/releases/$version/catalogd.yaml \
| yq eval ". | select(($duplicate_filter) | not)" \
> "$(dirname $0)/catalogd.yaml"
curl \
  --silent \
  --fail \
  -L https://github.com/operator-framework/catalogd/releases/$version/default-catalogs.yaml \
> "$(dirname $0)/catalogs.yaml"

curl \
  --silent \
  --fail \
  -L https://github.com/operator-framework/operator-controller/releases/$version/operator-controller.yaml \
| yq eval ". | select(($duplicate_filter) | not)" \
> "$(dirname $0)/operator-controller.yaml"

echo "Updated OLM"
