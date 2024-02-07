# Traefik Forward Auth

## Usage

1. Include this dir in your kustomization
1. Create a new client in your OIDC provider
1. Create a Secret named `oidc`
   - `issuer_url: ???`
   - `client_id: ???`
   - `client_secret: ???`
1. Create a ConfigMap named `forward-auth`
   - `config.ini`
     - `logout-redirect`
