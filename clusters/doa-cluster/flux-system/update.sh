#!/usr/bin/env bash

GITHUB_TOKEN="$(op item get 'Github PAT - dudeofawesome' --fields label=token)" \
  flux bootstrap github \
    --owner=dudeofawesome \
    --repository=doa-cluster-flux \
    --branch=main \
    --path=clusters/doa-cluster \
    --personal
