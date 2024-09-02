#!/usr/bin/env bash

version="latest/download"
if [ -n "$1" ]; then
  echo "Updating to version $1"
  version="download/$1"
fi

curl \
  --silent \
  -L https://github.com/operator-framework/operator-lifecycle-manager/releases/$version/olm.yaml \
> "$(dirname $0)/olm.yaml"
curl \
  --silent \
  -L https://github.com/operator-framework/operator-lifecycle-manager/releases/$version/crds.yaml \
> "$(dirname $0)/crds.yaml"

echo "Updated OLM"
