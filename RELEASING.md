# Releasing Vestrix

## Versioning

Vestrix follows [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`, with tags named `vMAJOR.MINOR.PATCH`.

| Bump | When | Examples |
|---|---|---|
| **patch** `0.3.0 → 0.3.1` | Bug fixes only. Nothing a user relies on changes. | wrong call resolution, layout glitch, crash on odd syntax |
| **minor** `0.3.1 → 0.4.0` | New features, and while we're below 1.0 also changes that break CLI flags or the JSON format (called out under **Changed**) | a new view, a framework adapter, runtime tracing |
| **major** `0.x → 1.0.0` | The CLI, the `vestrix json` format and the viewer URL scheme are declared stable. After 1.0, any breaking change needs a major bump. | |

The version is defined in one place: `VERSION` in `vestrix/analyzer.py`. `pyproject.toml`, `vestrix --version`,
the viewer and the release workflow all read it from there.

## Release cycle

- **`main` is always releasable.** Work on a branch, open a pull request, and merge when CI is green.
- **Every PR updates `CHANGELOG.md`** by adding a line under `## [Unreleased]`, in *Added / Changed / Fixed / Removed*.
- **Patch releases** go out whenever a fix lands that users are waiting for.
- **Minor releases** go out every 2–4 weeks, or sooner, once `Unreleased` has a feature worth shipping.
- **Hotfix:** fix it on `main` and cut a patch right away. There are no long-lived release branches until 1.0.

## Cutting a release

```bash
git checkout main && git pull
python scripts/release.py bump minor --dry-run   # preview: version change, notes, tests
python scripts/release.py bump minor --push      # or: patch / major
```

`bump` refuses to run if the tree is dirty, you're not on `main`, the tag already exists, `Unreleased` is empty,
or tests fail. Otherwise it:

1. bumps `VERSION`
2. moves the `Unreleased` notes to a dated `## [X.Y.Z]` section and updates the compare links
3. commits `Release vX.Y.Z` and creates the annotated tag `vX.Y.Z`
4. with `--push`, pushes `main` and the tag

The tag starts `.github/workflows/release.yml`, which:

1. checks that the tag matches `VERSION`
2. runs the tests
3. builds the wheel, the sdist and a demo HTML page
4. publishes a GitHub Release, with the matching CHANGELOG section as its notes

## Installing a release

```bash
pip install "git+https://github.com/Tejas-Sinroja/Vestrix@v0.3.0"
# or download the .whl from the Releases page and: pip install vestrix-0.3.0-py3-none-any.whl
```

## If something goes wrong

- **The workflow failed before publishing:** fix the problem on `main`, then delete the tag and cut the next patch.
  Don't reuse a version number that anyone may already have pulled:
  `git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`
- **A bad release is out:** ship a fixed patch release, and mark the bad one as such in its GitHub Release notes.
