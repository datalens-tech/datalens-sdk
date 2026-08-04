# Design guide

Read this when the user asks to make a chart or dashboard look good, or when
choosing visual encodings. This is a **design guide, not an API reference**:
it says *what* to build so the result reads well. For the mechanics — which
methods to call, wire formats, lifecycle — go to the chart and dashboard
references listed at the end.

The SDK will persist any technically valid object, but "valid" is not "good".
These rules are the difference between a chart that renders and a chart that
communicates.

## Where calculations live

- **Reusable business logic belongs in the dataset, not in charts.** Add
  shared calculations with the dataset update DSL
  (`ds.update.add_calculation(...)`). When the definition changes, you fix
  one formula instead of hunting it down in every chart.
- **Chart-local fields are for one-off, chart-specific needs only** — a
  presentation-only ratio, a label tweak for a single visualization
  (`.add_local_field(title=..., formula=...)` on a chart builder). The
  moment a second chart needs the field, move it into the dataset.
- **Comment complex formulas.** Six months later nobody remembers why the
  denominator excludes weekends.
- **Prefer more datasets over one overloaded dataset.** Piles of LOD and
  table calculations are hard to debug and slow to run; push heavy logic
  toward the source.
- **Store dates as dates** in the source (not as text), and sort or
  partition the table by that column.

## Color

- **Never ship the default palette unconsidered.** A wall of identical
  default-blue bars says "nobody designed this". Choose the palette
  deliberately and match its kind to the field kind:
  - **dimension** → discrete palette: `.color_by_dimension(field)` plus
    `.palette(id=...)` with a discrete palette id;
  - **measure** → gradient palette: `.color_by_measure(field, palette=...)`
    with a gradient palette id.
- **At most 7 colors per chart.** Beyond that, hues stop being
  distinguishable and the legend becomes a lookup table. For
  high-cardinality dimensions, show TOP-N and roll the tail into a single
  "other" bucket (rank in a dataset calculation, then color by the bucketed
  field).
- **One color language per dashboard.** If several dimensions are colored
  across one dashboard (category, region, segment), give each dimension its
  own non-overlapping set of colors. Reusing the same hues for different
  dimensions makes readers infer relationships that do not exist ("these
  two are the same blue, so they must be related").
- **A single measure needs no rainbow.** Keep it neutral; save saturated
  color for the one element the eye should find first.

## Titles: exactly one

Every chart needs a visible title — and exactly one. The entry `name=` is a
catalog label, not a caption on the canvas.

- **Standalone chart** (viewed outside a dashboard): set
  `.chart_title(text="...")`.
- **Chart on a dashboard**: the widget supplies the title —
  `add_chart(chart, title="...")` with the default `show_title=True`. Do
  not also set `.chart_title(...)` on the chart itself, or the reader sees
  the same words twice, once inside the canvas and once on the widget.
- **Do not restate the same words** in the chart title, an axis title, and
  a dashboard header above the widget. Every visible label must add
  information; duplicates are noise.
- **Indicators (metric charts)** follow the same rule: hide the inner
  measure name with `.measure_title_mode(mode="hide")` and let the widget
  title label the number — but then keep `show_title=True` in `add_chart`,
  or the indicator ends up with no label at all. Keep the default font
  size; an oversized indicator (`.font_size(size="l")`) shouts.

## Legend and axis hygiene

Hide what carries no information; label what does.

- **Legend**: if color encodes nothing (single series) or the categories
  are already labeled on an axis, hide it with `.legend(mode="hide")`. Keep
  it only when it is the reader's sole key to the colors.
- **Axis titles**: name the value axis with `.axis_title(...)` when the
  measure is not obvious from the chart title; otherwise leave it off —
  one of the two must carry the name, not both.
- **Data labels**: label point values only where hovering is impossible or
  precision is required (PDF, print, wall screens). If every value is
  labeled, the value axis adds nothing — hide it with
  `.axis_visibility(..., mode="hide")`.
- **Gridlines**: keep the grid only on the axis a reader must decode
  numerically. Category axes never need one — disable it with
  `.grid(..., enabled=False)` for that placeholder. Mind that on
  horizontal bars the axes are swapped (categories on `y`, values on `x`),
  so the axis to silence flips too. If bars are labeled with values,
  the value-axis grid is also redundant.
- **Number formatting is set explicitly, never left to chance**:
  `.measure_format(field, format="percent", precision=1)`. A share shown
  as `0.3729` instead of `37.3%` is a bug, and default float precision is
  visual noise. Set format, precision, and units (`unit=`, `prefix=`,
  `postfix=`) for every displayed measure.
  Wizard `measure_format()` uses `format="number" | "percent" | "currency"`
  and `unit="auto" | "k" | "m" | "bln"`. Do not reuse dataset-field
  formatting literals here: dataset units include `"b"` and `"t"` instead
  of chart-side `"bln"`.
- **Do not mix measures of different scale on one axis.** Sales in the
  hundreds of thousands next to profit in the tens of thousands flattens
  the smaller series into an unreadable line at zero, and a second axis
  rarely saves it. Use two stacked charts, a combined chart (columns +
  line), or normalize to shares/indices. One axis = measures of one nature
  and one scale.
- **Time series**: truncate timestamps to a sensible grain with
  `DATETRUNC` in a formula rather than plotting thousands of raw points; a
  continuous date axis reads better than a discrete one.

## Tables for TOP-N

A TOP-N ranking reads better as a table than as a horizontal bar chart:
sorting, a row limit, and in-cell bars are more legible and do not distort
scale. On a flat table: `.add_sort(field, direction="desc")` +
`.pagination(enabled=True, limit=N)` + `.column_bars(field)`. Put bars on
measures only, never on dimensions. Add column hints that explain how each
metric is computed.

## Dashboard composition

Readers scan left-to-right, top-to-bottom; the layout must match that order:

1. **Selectors at the top** — the reader first sees what they control, then
   the result. Selectors below the charts are simply never found.
2. **KPI/indicator row** — the headline numbers.
3. **Details** — trends, breakdowns, tables.

- **Consistent grid sizes.** The grid is 36 columns wide and collapses
  widgets upward: an empty spot in a row makes neighbors float into it and
  the layout falls apart. Keep rows of equal height, fill each row's full
  width, and create intentional gaps with text spacers (`add_text`), not
  holes.
- **Names that say what and for whom.** Dashboard: "Pay card activation
  funnel in the app", not "Main dash Pay". Tabs: "KPI attainment by
  manager and region", not "KPI". Multi-word names are fine.
- **Every selector gets a `title=`.** An unlabeled selector forces the
  reader to guess what it filters. Group related selectors
  (`add_group_selector`), and connect selectors to each other only where a
  real dependency exists (region → city, one-directional); break
  meaningless links rather than letting everything filter everything.
- **Filter dates with a calendar selector**, not a dropdown of distinct
  dates.
- **One dashboard ≈ one screen.** Beyond that, split by tabs and by the
  reader's role — the less two roles overlap, the stronger the case for
  separate tabs.
- **Give the reader context, sparingly.** A dashboard header
  (`add_title`), metric descriptions in hints, and important disclaimers
  as text blocks (`add_text`) — but not a disclaimer on everything, or
  banner blindness sets in.

## Wizard-first

Prefer wizard charts; they are declarative, dataset-backed, and cheap to
maintain. QL charts are for ad-hoc, one-off looks at a query — do not build
production dashboards on them. Reach for an editor (custom JavaScript) chart
only when the wizard genuinely cannot express the requirement: most "I need
custom code" cases turn out to be a dataset calculation, chart tabs on the
dashboard, or a markdown widget. Every editor chart is code somebody has to
maintain forever.

## Related references

- [wizard-charts/_index.md](wizard-charts/_index.md) — routing to the 17
  wizard chart types and their mechanics.
- [dashboards.md](dashboards.md) — dashboard tabs, widgets, selectors, and
  layout mechanics.
