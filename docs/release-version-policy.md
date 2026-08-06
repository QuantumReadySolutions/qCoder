# qCoder Release Version Policy

Published qCoder versions are immutable. Distinct wheel or source-distribution bytes require a
distinct version identity, and no private build may reuse a version that is already published on
PyPI.

Every private release build must be traceable to its repository, branch, exact commit, and complete
SHA-256 artifact hashes. The package version must agree across `pyproject.toml`,
`qcoder.__version__`, built wheel metadata, and built source-distribution metadata.

Before publication, a superseding private candidate for an already used release identity must use
a PEP 440 local version in the form `<public-version>+wi<work-item>.<bounded-candidate-id>`. The
local identity is private, non-publishable proof material. The plain public version remains
reserved for the eventual frozen publication candidate and must not be assigned to another
intermediate byte set. Separately governed customer-facing surfaces may continue to name the
approved public version while it remains current, because customers never install a private
local-version candidate from an index; private proof installs the exact recorded archive by path
and hash. Candidate package documentation itself carries no stale public-version install pin.

The version-consistency proof must therefore distinguish the exact artifact identity from the
current public release. Authoritative package sources and distribution metadata must equal the
exact candidate identity. Candidate package documentation must not pin either an unpublished
candidate or a stale public version. When an external customer surface intentionally carries a
version pin, that pin must equal the current public release; candidate, rejected, or intervening
unpublished versions are forbidden.

Release proof must record the source commit, wheel hash, source-distribution hash, and publication
source. Private artifacts that reuse a published version are obsolete and must be either moved to a
clearly marked non-installable quarantine or recorded as absent. The official published artifact
must not be altered, renamed, moved, or quarantined.
