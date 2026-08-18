import { useEffect, useRef } from 'react';
import embed from 'vega-embed';

/**
 * Renders a Vega-Lite spec exactly as the backend produced it -- no
 * transformation needed, since visualization.py already emits valid
 * Vega-Lite JSON. Tooltips/zoom/pan come for free from vega-embed;
 * onMarkClick (optional) wires up click-to-drill without any extra
 * spec-side configuration.
 */
export default function VegaChart({ spec, onMarkClick, height }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!ref.current || !spec) return;
    let view;

    const themedSpec = {
      ...spec,
      config: {
        axis: { labelFont: 'IBM Plex Mono', labelColor: '#6B7280', titleFont: 'Inter', titleColor: '#1B2430', gridColor: '#EDEAE2' },
        legend: { labelFont: 'IBM Plex Mono', titleFont: 'Inter' },
        title: { font: 'Inter', fontWeight: 500, fontSize: 13, color: '#1B2430', anchor: 'start' },
        view: { stroke: 'transparent' },
      },
      background: 'transparent',
      ...(height ? { height } : {}),
    };

    embed(ref.current, themedSpec, { actions: false, renderer: 'svg' }).then((result) => {
      view = result.view;
      if (onMarkClick) {
        view.addEventListener('click', (event, item) => {
          if (item && item.datum) onMarkClick(item.datum);
        });
      }
    });

    return () => view && view.finalize();
  }, [spec, onMarkClick, height]);

  if (!spec) return null;
  return <div ref={ref} className={onMarkClick ? 'cursor-pointer' : ''} />;
}
