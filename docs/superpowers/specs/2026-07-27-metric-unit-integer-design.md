# Metric Unit Integer Conversion Design

## Goal

Prevent Chinese-unit count metrics such as `2.99万` from being stored as
floating-point artifacts such as `29900.000000000004`.

## Behavior

- Values ending in `万` or `亿` are parsed with `float`, multiplied by the
  corresponding unit multiplier, and immediately converted with `int`.
- `2.99万` becomes `29900`.
- Percentage values keep their existing floating-point behavior.
- Plain decimal values without a Chinese count unit keep their existing
  behavior.
- Invalid and non-numeric values keep their existing fallback behavior.

## Verification

Add regression coverage for `2.99万 == 29900` while retaining the existing
tests for `1.2万`, `3.5亿`, percentages, missing values, and duration strings.

