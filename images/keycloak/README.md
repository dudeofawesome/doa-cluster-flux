# Keycloak image

The image includes the `orleans` welcome theme and selects it with `KC_SPI_THEME__WELCOME_THEME`. It serves a fixed set of account and administration links at the server root. Login, account, admin, and email themes remain the Keycloak defaults.

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
