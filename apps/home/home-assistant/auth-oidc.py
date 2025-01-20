#!/usr/bin/env python3

from os import environ
from sys import argv, stderr
from httpx import get, post, Headers, HTTPStatusError
from jwt import decode


def login(
    *,
    oidc_issuer_url: str,
    oidc_client_id: str,
    oidc_client_secret: str,
    username: str,
    password: str,
    oidc_issuer_validate_cert=True,
):
  log(f"User '{username}' attempting to log in")

  openid_config = f"{oidc_issuer_url}/.well-known/openid-configuration"

  config_data = get(
      openid_config,
      follow_redirects=True,
  ).raise_for_status().json()

  token_endpoint = config_data['token_endpoint']

  try:
    res = post(
        token_endpoint,
        headers=Headers(
            {
                'content-type': 'application/x-www-form-urlencoded',
            }
        ),
        data={
            'client_id': oidc_client_id,
            'client_secret': oidc_client_secret,
            'grant_type': 'password',
            'username': username,
            'password': password,
        },
        verify=oidc_issuer_validate_cert,
        follow_redirects=True,
    ).raise_for_status().json()
  except HTTPStatusError as err:
    if err.response.status_code == 401:
      log(f"Failed login attempt for user '{username}'")
      exit(77)
    else:
      log(f"Unknown error with HTTP status {err.response.status_code}")
      log(err.response.text)
      exit(1)

  jwt_payload = decode(res['access_token'], options={'verify_signature': False})

  name = jwt_payload['name']
  roles = jwt_payload['resource_access']['realm-management']['roles']

  group = 'admin' if (
      'realm-admin' in roles or 'home-assistant-admin' in roles
  ) else 'users'

  log(f"User '{username}' successfully authenticated, with group {group}")

  print(f"name = {name}")
  print(f"group = {group}")
  print(f"local_only = false")


def log(payload):
  message = f"auth-oidc.py: {payload}"
  print(message, file=stderr)


def arr_get(lst, index, default=None):
  try:
    return lst[index]
  except IndexError:
    return default


login(
    oidc_issuer_url=environ.get('oidc_issuer_url', arr_get(argv, 1)),
    oidc_issuer_validate_cert=(
        environ.get('oidc_issuer_validate_cert', arr_get(argv, 2,
                                                         'false')) == 'true'
    ),
    oidc_client_id=environ.get('oidc_client_id', arr_get(argv, 3)),
    oidc_client_secret=environ.get('oidc_client_secret', arr_get(argv, 4)),
    username=environ.get('username', arr_get(argv, 5)),
    password=environ.get('password', arr_get(argv, 6)),
)
