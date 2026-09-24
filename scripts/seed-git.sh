#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "Seeding Git repository..."
TMP_DIR=$(mktemp -d)
cd "${TMP_DIR}"

git init -b main
GIT_USER_NAME="$(git config user.name 2>/dev/null || echo 'Platform Engineer')"
GIT_USER_EMAIL="$(git config user.email 2>/dev/null || echo 'platform-team@local')"
git config user.name "${GIT_USER_NAME}"
git config user.email "${GIT_USER_EMAIL}"

cp -r "${ROOT_DIR}/charts" .
cp -r "${ROOT_DIR}/gitops" .
cp -r "${ROOT_DIR}/remediator" .
cp -r "${ROOT_DIR}/monitoring" .

git add .
git commit -m "Initial GitOps repository seed: v1.0.0"

echo "Pushing to git://127.0.0.1:30080/repo.git..."
git push git://127.0.0.1:30080/repo.git main --force

echo "Pushing second commit to establish Git revision history..."
echo "# Autonomous GitOps Platform" > README.md
git add README.md
git commit -m "docs: add platform overview (v1.0.1)"
git push git://127.0.0.1:30080/repo.git main

cd /
rm -rf "${TMP_DIR}"
echo "Seeding complete!"
