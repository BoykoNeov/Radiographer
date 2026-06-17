// `plotly.js-basic-dist-min` ships no own types. It is the same Plotly API as the
// full bundle (scatter for M6c curves + bar for M6f dose breakdown), so we re-export
// the upstream `@types/plotly.js` surface for it. The basic bundle's default export
// is the Plotly object (`Plotly.react`, `Plotly.newPlot`, `Plotly.purge`, …).
declare module "plotly.js-basic-dist-min" {
  import Plotly = require("plotly.js");
  export = Plotly;
}
