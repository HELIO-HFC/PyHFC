#!/bin/sh
# SPDX-License-Identifier: EUPL-1.2
#
# Check that a tag can be published on PyPI:
#   - the tag must match the version of the package (X.Y.Z or vX.Y.Z),
#   - the tagged commit must be on the master branch (which receives the releases).
#
# Usage: ci/check-release.sh TAG COMMIT
# The full git history is needed (no shallow clone).
set -eu

tag=$1
commit=$2
version=$(uv version --short)

if [ "$tag" != "$version" ] && [ "$tag" != "v$version" ]; then
    echo "ERROR: the tag $tag does not match the version of the package ($version)" >&2
    exit 1
fi

git fetch --quiet origin master
if ! git merge-base --is-ancestor "$commit" FETCH_HEAD; then
    echo "ERROR: the tagged commit $commit is not on the master branch" >&2
    exit 1
fi

echo "Version $version ($tag) can be published"
