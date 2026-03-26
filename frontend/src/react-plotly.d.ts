declare module "react-plotly.js" {
  import { Component } from "react";
  import Plotly from "plotly.js-dist-min";

  interface PlotParams {
    data: Plotly.Data[];
    layout?: Partial<Plotly.Layout>;
    config?: Partial<Plotly.Config>;
    frames?: Plotly.Frame[];
    useResizeHandler?: boolean;
    style?: React.CSSProperties;
    className?: string;
    onInitialized?: (figure: Readonly<{ data: Plotly.Data[]; layout: Plotly.Layout }>, graphDiv: HTMLElement) => void;
    onUpdate?: (figure: Readonly<{ data: Plotly.Data[]; layout: Plotly.Layout }>, graphDiv: HTMLElement) => void;
    onRelayout?: (event: Plotly.PlotRelayoutEvent) => void;
    onClick?: (event: Plotly.PlotMouseEvent) => void;
    onSelected?: (event: Plotly.PlotSelectionEvent) => void;
    revision?: number;
  }

  class Plot extends Component<PlotParams> {}
  export default Plot;
}

declare module "plotly.js-dist-min" {
  export * from "plotly.js";
}
