## Project Overview

Kubernetes K3s cluster, managed with gitops via FluxCD, with Operator Lifecycle Manager v1, cert-manager, Traefik

**Do not** modify cluster state without explicit permission (explicit command "deploy changes"). Updates to deployed resources must always go through git

Run non-basic commands from inside the devenv (`devenv shell --quiet -- {command}`), which will not work in a sandbox.
