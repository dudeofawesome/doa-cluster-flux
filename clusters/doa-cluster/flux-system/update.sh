#!/usr/bin/env bash

GITHUB_TOKEN="$(op read 'op://Private/4w4ctwnyxvw4wdtpymrgf4xvoy/credential')" \
  flux bootstrap github \
    --owner=dudeofawesome \
    --repository=doa-cluster-flux \
    --branch=main \
    --path=clusters/doa-cluster \
    --personal \
    $@
