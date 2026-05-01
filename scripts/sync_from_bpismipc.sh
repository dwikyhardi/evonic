#!/usr/bin/env bash

HOST=100.89.19.95

rsync -avzrhcP \
  --exclude=__pycache__ \
  --exclude=node_modules \
  --exclude=.git \
  --exclude=logs/ \
  --exclude=.venv/ \
  --exclude=.pip_pkgs/ \
  --exclude=scripts/sync_from_bpismipc.sh \
  --exclude=*.db \
  --exclude=plan/ \
  --exclude=tmp/ \
  --exclude=db/ \
  --exclude=db* \
  --exclude=skills/claimguard \
  robin@$HOST:dev/evonic/ /Users/robin/Development/evonic
