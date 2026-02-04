#!/bin/bash
set -ex

# We create the virtualenv separately from the "pip install" commands below,
# to make error-reporting a bit more obvious. We also update beforehand,
# beyond what the system version provides, see #6317.
python3 -m venv /tmp/securedrop-app-code-i18n-ve
/tmp/securedrop-app-code-i18n-ve/bin/pip3 install -r \
<(echo "pip==26.0 \
--hash=sha256:3ce220a0a17915972fbf1ab451baae1521c4539e778b28127efa79b974aff0fa \
--hash=sha256:98436feffb9e31bc9339cf369fd55d3331b1580b6a6f1173bacacddcf9c34754")

source /etc/os-release

# Install dependencies
/tmp/securedrop-app-code-i18n-ve/bin/pip3 install --no-deps --no-binary :all: --require-hashes -r requirements/translation-requirements.txt

# Compile the translations
. /tmp/securedrop-app-code-i18n-ve/bin/activate
pybabel compile --directory translations/
