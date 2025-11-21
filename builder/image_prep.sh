set -euxo pipefail
# Build the container if necessary. This runs *outside* the container.

cd "$(git rev-parse --show-toplevel)"

if [[ $OS_VERSION == "trixie" ]]; then
    BASE_IMAGE="debian:${OS_VERSION}"
else
    BASE_IMAGE="ubuntu:${OS_VERSION}"
fi

# This script can be run with the argument "admin" to build the admin container.
BUILDER_TYPE="${1:-server}"
IMAGE_NAME="fpf.local/sd-${BUILDER_TYPE}-builder-${OS_VERSION}"
DOCKERFILE="builder/${BUILDER_TYPE}Dockerfile"

# First see if the image exists or not
missing=false
$OCI_BIN inspect "${IMAGE_NAME}" > /dev/null 2>&1 || missing=true

if $missing; then
    # Build it if it doesn't
    $OCI_BIN build \
        -f "${DOCKERFILE}" \
        --build-arg=BASE_IMAGE="${BASE_IMAGE}" \
        -t "${IMAGE_NAME}" builder/ --no-cache
fi

# Uncomment the following for fast development on adjusting builder logic
$OCI_BIN build -f "${DOCKERFILE}" --build-arg=BASE_IMAGE="${BASE_IMAGE}" -t "${IMAGE_NAME}" builder/

# Run the dependency check
status=0
$OCI_BIN run --rm $OCI_RUN_ARGUMENTS \
    --entrypoint "/dep-check" "${IMAGE_NAME}" || status=$?

if [[ $status == 42 ]]; then
    # There are some pending updates, so force rebuilding the image from scratch
    # and try again!
    echo "Rebuilding container to update dependencies"
    $OCI_BIN rmi "${IMAGE_NAME}"
    $OCI_BIN build -f "${DOCKERFILE}" --build-arg=BASE_IMAGE="${BASE_IMAGE}" \
        -t "${IMAGE_NAME}" builder/ --no-cache
    # Reset $status and re-run the dependency check
    status=0
    $OCI_BIN run --rm $OCI_RUN_ARGUMENTS \
        --entrypoint "/dep-check" "${IMAGE_NAME}" || status=$?
fi

if [[ $status != 0 ]]; then
    # If there's some other error, exit now
    exit $status
fi
