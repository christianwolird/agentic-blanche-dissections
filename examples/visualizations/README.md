# Visualization examples

These images were generated from real task entries using `msolve 0.10.1` and
the default bilinear presentation. Congruency classes were computed exactly
in each RUR number field; only rectangle placement used numerical
approximations.

| Database task | Real solutions | Exact congruency partitions |
|---|---:|---|
| `E6`, sequence 1, `e60b770fd06a237e855d4388` | 2 degree-2 | Both `5=4+1` |
| `E8`, sequence 1, `4e6514469bf044184dfd8049` | 1 degree-1; 2 degree-2 | Rational: `7=2+2+2+1`; irrational: `7=1+...` |
| `E11`, sequence 10, `61ae9ad813519ec10bbaf34f` | 1 degree-1; 6 degree-6 | Rational: `10=2+2+2+2+1+1`; irrational: `10=1+...` |

The SVG files are the tool's native output. The PNG files are preview copies
of the same images.

For example:

```bash
python tools/visualize_task.py results/E8.sqlite \
  4e6514469bf044184dfd8049 \
  --output examples/visualizations/E8-4e651446.svg
```
