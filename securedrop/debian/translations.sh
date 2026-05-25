#!/bin/bash
set -ex

# We create the virtualenv separately from the "pip install" commands below,
# to make error-reporting a bit more obvious. We also update beforehand,
# beyond what the system version provides, see #6317.
python3 -m venv /tmp/securedrop-app-code-i18n-ve
/tmp/securedrop-app-code-i18n-ve/bin/pip3 install -r \
<(echo "pip==26.1.1 \
    --hash=sha256:99cb1c2899893b075ff56e4ed0af55669a955b49ad7fb8d8603ecdaf4ed653fb \
    --hash=sha256:d36762751d156a4ee895de8af39aa0abeeeb577f93a2eca6ab62467bbf0f8a78")

source /etc/os-release

# Install dependencies
/tmp/securedrop-app-code-i18n-ve/bin/pip3 install --no-deps --no-binary :all: --require-hashes -r requirements/translation-requirements.txt

# Compile the translations
. /tmp/securedrop-app-code-i18n-ve/bin/activate
pybabel compile --directory translations/
