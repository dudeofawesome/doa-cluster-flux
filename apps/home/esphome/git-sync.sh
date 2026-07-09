#!/bin/sh
set -eu

repo_dir="${GIT_REPO_DIR:-/config}"
remote="${GIT_REMOTE:?GIT_REMOTE is required}"
branch="${GIT_BRANCH:-main}"
interval="${GIT_SYNC_INTERVAL:-300}"
ssh_dir="/tmp/git-ssh"

log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

setup_ssh() {
  mkdir -p "${ssh_dir}"
  cp /etc/git-secret/identity "${ssh_dir}/identity"
  chmod 0400 "${ssh_dir}/identity"

  if [ -f /etc/git-secret/known_hosts ]; then
    cp /etc/git-secret/known_hosts "${ssh_dir}/known_hosts"
  else
    touch "${ssh_dir}/known_hosts"
  fi

  export GIT_SSH_COMMAND="ssh -i ${ssh_dir}/identity -o UserKnownHostsFile=${ssh_dir}/known_hosts -o StrictHostKeyChecking=yes"
}

setup_repo() {
  mkdir -p "${repo_dir}"
  cd "${repo_dir}"

  git config --global --add safe.directory "${repo_dir}"

  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "${repo_dir} is not a git repository; refusing to initialize it"
    exit 1
  fi

  if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "${remote}"
  else
    git remote add origin "${remote}"
  fi

  {
    printf '%s\n' '.esphome/build/'
    printf '%s\n' '.esphome/platformio/'
    printf '%s\n' '.esphome/.pioenvs/'
    printf '%s\n' '.esphome/.piolibdeps/'
    printf '%s\n' '__pycache__/'
  } > .git/info/exclude
}

sync_once() {
  cd "${repo_dir}"

  if git ls-remote --exit-code --heads origin "${branch}" >/dev/null 2>&1; then
    if ! git pull --rebase --autostash origin "${branch}"; then
      git rebase --abort >/dev/null 2>&1 || true
      log "pull failed; leaving working tree unchanged"
      return 1
    fi
  fi

  if ! git rev-parse --verify HEAD >/dev/null 2>&1; then
    log "no commits to push"
    return 0
  fi

  if ! git push -u origin "HEAD:${branch}"; then
    log "push failed; will retry after fetching remote changes"
    git fetch origin "${branch}" || true
    git pull --rebase --autostash origin "${branch}" || return 1
    git push -u origin "HEAD:${branch}"
  fi
}

setup_ssh
setup_repo

while true; do
  sync_once || true
  sleep "${interval}"
done
