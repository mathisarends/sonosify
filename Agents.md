# Repository conventions

- Prefix module-level constants, helpers, and other symbols with `_` when they
  are not part of the supported public API. Do not define `__all__`; distinguish
  public and private APIs through naming alone. Do not re-export endpoint URLs,
  environment-variable names, cache-path helpers, or similar implementation
  details unless callers genuinely need them as part of the supported API.
- Do not add comments or docstrings that merely repeat a class name, function
  name, parameter list, return type, or immediately visible control flow in
  prose. Document rationale, constraints, security implications, protocol
  details, and other non-obvious behavior only.
