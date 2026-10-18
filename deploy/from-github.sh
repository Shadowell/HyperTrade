#!/usr/bin/env bash
set -Eeuo pipefail

# Root-owned forced-command entrypoint for GitHub-hosted HyperTrade deploys.
# The caller can only pass a 40-hex SHA; code is fetched from the public mirror.

root=/opt/hypertrade
mirror="$root/deploy/github.git"
lock="$root/deploy/from-github.lock"
sha="${SSH_ORIGINAL_COMMAND:-${1:-}}"

fail() {
  printf 'from-github: %s\n' "$1" >&2
  exit 2
}

[ "$(id -u)" -eq 0 ] || fail 'must run as root'
case "$sha" in
  *[!0-9a-f]*|'') fail 'invalid SHA' ;;
esac
[ "${#sha}" -eq 40 ] || fail 'invalid SHA length'
[ -d "$mirror" ] || fail 'trusted mirror missing'

exec 9>"$lock"
flock -w 1800 9

git --git-dir="$mirror" fetch --no-tags --force origin '+refs/heads/main:refs/remotes/origin/main'
remote_sha="$(git --git-dir="$mirror" rev-parse refs/remotes/origin/main)"
[ "$remote_sha" = "$sha" ] || fail 'SHA is not the current main'
[ "$(git --git-dir="$mirror" cat-file -t "$sha")" = commit ] || fail 'not a commit'

if [ "$(cat "$root/deploy/last_deployed_sha" 2>/dev/null || true)" = "$sha" ]; then
  echo "HyperTrade $sha is already deployed"
  exit 0
fi

work="$(mktemp -d "$root/deploy/.github-$sha.XXXXXX")"
trap 'rm -rf "$work"' EXIT
git --git-dir="$mirror" archive --format=tar "$sha" | tar -C "$work" -xf -
[ -f "$work/deploy/deploy.sh" ] || fail 'release is missing deploy/deploy.sh'

cd "$work"
npm exec --yes pnpm@10 -- -C frontend install --frozen-lockfile
npm exec --yes pnpm@10 -- -C frontend build

rsync -a --delete \
  --exclude '.git' \
  --exclude '.venv' \
  --exclude '.pytest_cache' \
  --exclude 'frontend/node_modules' \
  --exclude 'frontend/dist' \
  --exclude '.env' \
  --exclude 'data' \
  --exclude 'logs' \
  --exclude 'workspace' \
  --exclude 'deploy/last_deployed_sha' \
  --exclude 'deploy/from-github.sh' \
  --exclude 'deploy/from-github.lock' \
  --exclude 'deploy/github.git/' \
  --exclude '/backups/' \
  ./ "$root/"
rsync -a --delete frontend/dist/ "$root/frontend/dist/"

chmod +x "$root/deploy/deploy.sh"
"$root/deploy/deploy.sh"
printf '%s\n' "$sha" > "$root/deploy/last_deployed_sha"
