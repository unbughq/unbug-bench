---
colors:
  paper: "#FCFCFA"
  ink: "#15171C"
  ink-secondary: "#474C57"
  ink-tertiary: "#6A707C"
  rule: "#D7D9DE"
  rule-light: "#ECEDF0"
  connector: "#C7CAD1"
  harm-rule: "#E2B8B2"
  endpoint-blue: "#1D4F91"
  endpoint-tint: "#E9EFF8"
  harm-red: "#A3261C"
  harm-tint: "#F8E9E7"
typography:
  title:
    fontFamily: Source Serif 4
    fontSize: 40px
    fontWeight: 600
    lineHeight: 1.12
    letterSpacing: -0.02em
  section:
    fontFamily: Source Serif 4
    fontSize: 28px
    fontWeight: 600
    lineHeight: 1.2
  body:
    fontFamily: Source Serif 4
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.6
  figure-label:
    fontFamily: Source Sans 3
    fontSize: 13px
    fontWeight: 700
    letterSpacing: 0.06em
  caption:
    fontFamily: Source Sans 3
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.5
  verdict:
    fontFamily: Source Sans 3
    fontSize: 19px
    fontWeight: 600
  note:
    fontFamily: Source Serif 4
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.55
  ui:
    fontFamily: Source Sans 3
    fontSize: 14px
    fontWeight: 600
  axis:
    fontFamily: Source Sans 3
    fontSize: 12px
    fontWeight: 400
  body-mobile:
    fontFamily: Source Serif 4
    fontSize: 17px
    fontWeight: 400
  section-mobile:
    fontFamily: Source Serif 4
    fontSize: 24px
    fontWeight: 600
  title-min:
    fontFamily: Source Serif 4
    fontSize: 30px
    fontWeight: 600
rounded:
  control: 999px
spacing:
  section: 64px
  page-gutter: 40px
  measure: 68ch
components:
  endpoint-panel:
    textColor: "{colors.ink}"
    padding: 16px 0
  grade-toggle:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
---

# Design System: unbug-bench reports

## Overview

Benchmark reports are written as pre-registered trial readouts, not leaderboards. The hypothesis and its margin appear before any result; every result carries its interval; the grader's own errors have a numbered log. White journal paper, near-black ink, hairline rules, numbered figures with sans captions. Mode: Read. Light by default for reading and printing; a dark theme for night reading. A Light / Dark / Auto switcher in the running head follows the system setting on Auto and remembers the choice in the browser. Print is always light.

## Colors

### Primary
- **Endpoint blue** (`#1D4F91`): the hypothesis, its margin line, deviation numbers, links and focus. Nothing else.

### Secondary
- **Harm red** (`#A3261C`): violations only. Failed checkpoints, the inferiority region (as `#F8E9E7` tint), a regraded-wrong box.

### Neutral
- Paper `#FCFCFA`, ink `#15171C`, secondary ink `#474C57`, tertiary `#6A707C`, rules `#D7D9DE`.

### Named Rules
- **Pass is ink, not green.** A passed checkpoint is a filled ink square; color is spent only on harm and on the hypothesis.
- **Status is ruled text, not a badge.** "Status: pilot" sits between two hairlines under the byline.

### Dark theme
Paper `#121418`, ink `#E7E8EB`, secondary `#B4B8C1`, tertiary `#8C929D`, rules `#2F333B` / `#22252B`, endpoint blue `#86ADE8`, harm red `#F0897F` with tint `#2B1816`, surface `#181B20`. Every chart reads these as CSS variables, so charts follow the theme.

## Typography

Source Serif 4 for title, sections and body; Source Sans 3 for every figure, table, caption and label, with tabular lining numerals. Fonts are embedded so the file works offline and prints.

### Hierarchy
Title 30–40px/600, with the subtitle on its own line in 22–27px secondary ink · Section 28px/600 · Body 18px/1.6 at a 68ch measure · Figure labels 13px/700 uppercase tracked 0.06em · Captions 15px sans, beginning "Figure n. Title."

### Named Rules
- **Captions carry the method.** Every figure says what the mark, the interval and the shading mean.

## Layout

1180px page, 40px gutters. The opening is a two-column lead: title and structured abstract (Background, Methods, Results, Conclusions) on the left, the sticky primary-endpoint panel with a miniature forest plot on the right. Below 980px the endpoint panel moves between title and abstract. Wide tables scroll horizontally inside their own container rather than squeezing.

## Elevation & Depth

Flat and square-cornered. Hierarchy comes from rules: a 3px blue rule opens the endpoint panel, 1px ink under table headers, 1px light rules between rows. No shadows, no rounded panels; only the grade toggle is a pill.

## Components

- **Endpoint panel:** opened by a 3px blue rule and closed by a 1px blue rule; numbered endpoints, a verdict line, a miniature forest plot, and a human-time bar with the 30% requirement marked (left empty when it cannot be computed).
- **Flow diagram:** CONSORT-style vertical boxes joined by arrows, with exclusions, additions and corrections as side boxes on connector lines.
- **Checkpoint matrix:** contestants × steps for each round; ink square pass, red cross fail, dashed square not run; a radio toggle switches original and corrected grades.
- **Forest plot:** square for the observed difference, line with caps for the 95% interval, dashed blue margin, red-tinted inferiority region.
- **Deviation log:** D1…Dn, each with what happened and a correction column.
- **Notes:** numbered footnotes for caveats on a number, linked by superscript.

## Do's and Don'ts

- Do link highlighting across figures: hovering or focusing a contestant dims the others everywhere.
- Do compute every number from the run data at build time; never type a result by hand.
- Don't put a winner or a hero metric at the top.
- Don't use color for pass, or for decoration.
