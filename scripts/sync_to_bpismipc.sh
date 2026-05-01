#!/usr/bin/env bash

HOST=100.89.19.95

rsync -avzrhcP \
  --exclude=__pycache__ \
  --exclude=node_modules \
  --exclude=.git \
  --exclude=logs/ \
  --exclude=*.db \
  --exclude=skills \
  --exclude=scripts/sync_from_bpismipc.sh \
  /Users/robin/Development/evonic/ robin@$HOST:dev/evonic
