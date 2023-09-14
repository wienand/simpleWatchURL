#!/bin/sh
# Script uses local directory to store cache and responses from urls
cd "$(dirname "$0")" || exit
python3 watchURL.py --interval 57 \
  --from-address [ACCOUNT]@gmail.com \
  --smtp-server smtp.gmail.com \
  --smtp-username [ACCOUNT]@gmail.com \
  --smtp-password [GENERATED APP PASSWORD] \
  --to-recipients [ACCOUNT]@gmail.com --to-recipients [ACCOUNT]+SECOND@gmail.com \
  --bcc-recipients [ACCOUNT]+BCC@gmail.com \
  -u "https://www.random.org/integers/?num=2&min=1&max=3&col=1&base=10&format=html&rnd=new"\
  -u "https://www.random.org/integers/?num=4&min=1&max=3&col=1&base=10&format=html&rnd=new" \
  -u "https://www.random.org/integers/?num=8&min=1&max=3&col=1&base=10&format=html&rnd=new" \
  --verbose