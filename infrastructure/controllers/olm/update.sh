#!/usr/bin/env bash

curl \
  --silent \
  -L https://github.com/operator-framework/operator-lifecycle-manager/releases/latest/download/olm.yaml \
> "$(dirname $0)/olm.yaml"
curl \
  --silent \
  -L https://github.com/operator-framework/operator-lifecycle-manager/releases/latest/download/crds.yaml \
> "$(dirname $0)/crds.yaml"

echo "Updated OLM"
