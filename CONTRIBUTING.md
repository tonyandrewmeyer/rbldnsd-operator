# Contributing

To make contributions to this charm, you'll need a working
[development setup](https://documentation.ubuntu.com/juju/3.6/howto/manage-your-deployment/#set-up-your-deployment-local-testing-and-development).

## Testing

This project uses `tox` (with `tox-uv`) for managing test environments. The
environments install from the project's `uv.lock` to ensure deterministic
tool versions. Pre-configured environments:

```shell
tox run -e format        # update your code according to linting rules
tox run -e lint          # ruff + codespell + ty
tox run -e unit          # unit tests
tox run -e integration   # integration tests (requires a `.charm` to deploy)
tox                      # runs 'format', 'lint', and 'unit' environments
```

Install `tox-uv` first if you don't have it:

```shell
uv tool install tox --with tox-uv
```

## Build the charm

Build the charm in this git repository using:

```shell
charmcraft pack
```

## Integration tests

The integration tests look for a `.charm` file in the project root, or honour
the `CHARM_PATH` environment variable. `pytest-jubilant` provides a
module-scoped `juju` fixture that creates and tears down a Juju model per
test file. Run the tests after packing the charm:

```shell
charmcraft pack
tox -e integration
```
