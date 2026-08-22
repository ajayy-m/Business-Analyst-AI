const BASE = '/api';

async function handle(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON -- keep statusText
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function uploadFile(datasetId, tableName, file) {
  const form = new FormData();
  form.append('table_name', tableName);
  form.append('file', file);
  const res = await fetch(`${BASE}/datasets/${datasetId}/upload`, {
    method: 'POST',
    body: form,
  });
  return handle(res);
}

export async function listDatasets() {
  const res = await fetch(`${BASE}/datasets`);
  return handle(res);
}

export async function getCatalog(datasetId) {
  const res = await fetch(`${BASE}/datasets/${datasetId}/catalog`);
  return handle(res);
}

export async function askQuestion(datasetId, question) {
  const form = new URLSearchParams({ question });
  const res = await fetch(`${BASE}/datasets/${datasetId}/ask`, {
    method: 'POST',
    body: form,
  });
  return handle(res);
}

export async function diagnoseDirect(datasetId, metricColumn, dateColumn, filters) {
  const form = new URLSearchParams({
    metric_column: metricColumn,
    date_column: dateColumn,
    filters_json: JSON.stringify(filters || {}),
  });
  const res = await fetch(`${BASE}/datasets/${datasetId}/diagnose`, {
    method: 'POST',
    body: form,
  });
  return handle(res);
}

export async function getAnomalies(datasetId) {
  const res = await fetch(`${BASE}/datasets/${datasetId}/anomalies`);
  return handle(res);
}

export async function getDashboard(datasetId, tableName, opts = {}) {
  const params = new URLSearchParams();
  if (tableName) params.set('table_name', tableName);
  if (opts.filters && Object.keys(opts.filters).length) params.set('filters_json', JSON.stringify(opts.filters));
  if (opts.dateFrom) params.set('date_from', opts.dateFrom);
  if (opts.dateTo) params.set('date_to', opts.dateTo);
  const qs = params.toString();
  const res = await fetch(`${BASE}/datasets/${datasetId}/dashboard${qs ? `?${qs}` : ''}`);
  return handle(res);
}

export async function getForecast(datasetId, metricColumn, dateColumn, periodsAhead = 3, granularity = 'month') {
  const form = new URLSearchParams({
    metric_column: metricColumn,
    date_column: dateColumn,
    periods_ahead: periodsAhead,
    granularity,
  });
  const res = await fetch(`${BASE}/datasets/${datasetId}/forecast`, {
    method: 'POST',
    body: form,
  });
  return handle(res);
}

export async function getChurn(datasetId, idColumn, metricColumn, dateColumn, topN = 20) {
  const form = new URLSearchParams({
    id_column: idColumn,
    metric_column: metricColumn,
    date_column: dateColumn,
    top_n: topN,
  });
  const res = await fetch(`${BASE}/datasets/${datasetId}/churn`, {
    method: 'POST',
    body: form,
  });
  return handle(res);
}