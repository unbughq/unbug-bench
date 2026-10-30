# D interface review relocation

Rebasing D onto `factory-simplify` at `6e7925e` exposed review filename
collisions with B. Both sets are preserved. B retains interfaces-design-15
through -18. D's verbatim reviews and responses moved as follows:

| Original D path | Current D path |
| --- | --- |
| interfaces-design-15.md | interfaces-design-19.md |
| interfaces-design-16.md | interfaces-design-20.md |
| interfaces-design-17.md | interfaces-design-21.md |
| interfaces-design-18.md | interfaces-design-22.md |

References and titles inside these verbatim reviews use the original D numbers.
The passing interface review is now `interfaces-design-22.md`; its reviewed
docs commit `6055678` rebased to `bec770b`. No review text was changed.
