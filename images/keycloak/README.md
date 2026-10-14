# Keycloak image

## Smoke test

Build and test locally with Docker running:

```sh
docker build \
  --file images/keycloak/Containerfile \
  --tag keycloak-welcome:test \
  --load \
  images/keycloak

python3 images/keycloak/smoke-test.py keycloak-welcome:test
```
