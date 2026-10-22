# Fixed timestamp releases

Application/plugin releases use America/New_York local `YY.MMDD.HHmmss`. Choose and stamp the
value once for a source checkpoint. Runtime startup, tests and packaging never read the clock
to invent another version. Do not reuse a published stamp for different release bytes; preserve
historical receipts, caches and artifacts. A repeated local clock/DST collision requires a new
unused stamp. Years represent 2000–2099; seconds are 00–59.

`release_version.py` retains the fully padded human `DISPLAY_VERSION`. `PACKAGE_VERSION` removes
leading zeroes from each of the same three numeric components, satisfying Python PEP 440 and
strict SemVer plugin metadata. For example, `26.0102.030405` displays unchanged and packages as
`26.102.30405`. These are the same release. Compare components numerically, not raw strings.
Preserve the display value: the canonical identity alone cannot reconstruct all padding without
the timestamp convention. Historical numeric releases such as `0.3.0` remain readable.

The CLI `--version`, service status and MCP information use the padded display value. Build and
plugin manifests, immutable plugin package/cache identity and manager component versions use the
canonical identity; management messages retain the padded display. The source byte manifest
stores both. This Python app ships no .NET assembly/file version; no oversized HHmmss component
is placed in a Windows assembly/file version field.

For an explicitly selected stamp:

```powershell
python scripts/stamp_release.py --timestamp 26.0102.030405
python scripts/stamp_release.py --verify
```

The stamper updates source, pyproject, both standalone plugin manifests and the current README.
Build in a new private directory named for that release, keeping old output intact. Regenerate
the byte manifest and source archive, then build the wheel/sdist from those fixed sources. Verify
wheel METADATA, imported `__version__`/`__package_version__`, CLI output and plugin metadata agree
semantically. Record the previous-to-new mapping, package hashes and evidence under ignored
`.local/` or outside the repository. Do not record machine receipts or live cache paths publicly.

Held profiles may build and inspect package bytes, but must not refresh installed environments,
live plugin caches, manager installation metadata or existing guidance publications. Installation
and runtime/native Codex acceptance are separate checks after authorization. Version stamping
does not alter the MCP SDK/protocol or independently reviewed framework dependency pins.
