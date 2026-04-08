(function(){
    // Helper function to get CSRF token from cookies
    function getCookie(name) {
      let cookieValue = null;
      if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
          const cookie = cookies[i].trim();
          if (cookie.substring(0, name.length + 1) === (name + '=')) {
            cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
            break;
          }
        }
      }
      return cookieValue;
    }
    
    // Get CSRF token from cookie
    function getCsrfToken() {
      return getCookie('csrftoken');
    }
    
    const API_ROOT = "/predictor/api/v1/";
    const LEGACY_API_ROOT = "/predictor/api/predictions/?type=";
    const chartEl = document.getElementById("predChart");
    const metaEl = document.getElementById("meta");
    const rangeLabel = document.getElementById("range-label");
    const buttons = document.querySelectorAll(".btn[data-type]");
    const refreshBtn = document.getElementById("refresh");
    const runForecastBtn = document.getElementById("run-forecast");
    const exportCsvBtn = document.getElementById("export-csv");
    const startInput = document.getElementById("start-date");
    const endInput = document.getElementById("end-date");
    const applyBtn = document.getElementById("apply");
    const clearBtn = document.getElementById("clear");
    const nextDayEl = document.getElementById("next-day");
    const nextDayLabel = document.getElementById("next-day-label");
    const nextWeekEl = document.getElementById("next-week");
    const nextMonthEl = document.getElementById("next-month");
    const totalPredictionsEl = document.getElementById("total-predictions");
    const progressContainer = document.getElementById("progress-container");
    const progressFill = document.getElementById("progress-fill");
    const progressText = document.getElementById("progress-text");
    const alertContainer = document.getElementById("alert-container");
    const forecastHistoryEl = document.getElementById("forecast-history");
    
    let active = "daily";
    let chart = null;
    let currentForecastRun = null;

    const toNum = v => (v === null || v === undefined) ? null : Number(v);
    const median = arr => { if(!arr.length) return 0; const s = arr.slice().sort((a,b)=>a-b); const m = Math.floor(s.length/2); return s.length%2 ? s[m] : (s[m-1]+s[m])/2; };

    function showAlert(message, type = 'success') {
      const alertDiv = document.createElement('div');
      alertDiv.className = `alert alert-${type}`;
      alertDiv.textContent = message;
      alertContainer.appendChild(alertDiv);
      
      setTimeout(() => {
        alertDiv.remove();
      }, 5000);
    }

    function showProgress(show = true) {
      progressContainer.style.display = show ? 'block' : 'none';
    }

    function updateProgress(percent, text) {
      progressFill.style.width = `${percent}%`;
      progressText.textContent = text;
    }

    async function fetchPred(type, start, end) {
      let url = API_ROOT + "predictions/?type=" + encodeURIComponent(type);
      const params = [];
      if (start) params.push("start_date=" + start);
      if (end) params.push("end_date=" + end);
      if (params.length) url += "&" + params.join("&");
      else url += "&upcoming=1";
      
      const r = await fetch(url);
      if (!r.ok) throw new Error("API " + r.status);
      const data = await r.json();
      
      // Handle paginated response - return results array directly
      return data.results || data;
    }

    async function fetchSummary(type) {
      const url = API_ROOT + "predictions/summary/?type=" + encodeURIComponent(type);
      const r = await fetch(url);
      if (!r.ok) throw new Error("Summary API " + r.status);
      return await r.json();
    }

    async function fetchForecastHistory() {
      const url = API_ROOT + "forecast-runs/?limit=10";
      const r = await fetch(url);
      if (!r.ok) throw new Error("History API " + r.status);
      const data = await r.json();
      
      // Handle paginated response - return results array directly
      return data.results || data;
    }

    function prepare(rows) {
      rows.sort((a,b) => new Date(a.date) - new Date(b.date));
      const labels = [], forecast = [], lower = [], upper = [], actual = [];
      for (const r of rows) {
        labels.push(r.date);
        forecast.push(toNum(r.predicted_value));
        lower.push(toNum(r.yhat_lower));
        upper.push(toNum(r.yhat_upper));
        actual.push(toNum(r.actual_value));
      }
      return { labels, forecast, lower, upper, actual };
    }

    function updateSummary(prep, summary = null) {
      const { labels, forecast } = prep;
      const today = new Date();
      const nextDay = new Date(today); nextDay.setDate(today.getDate() + 1);
      const next7 = new Date(today); next7.setDate(today.getDate() + 7);
      const next30 = new Date(today); next30.setDate(today.getDate() + 30);
      
      let tomorrowVal = null, weekSum = 0, monthSum = 0;
      for (let i = 0; i < labels.length; i++) {
        const d = new Date(labels[i]);
        const val = forecast[i] || 0;
        if (d.toDateString() === nextDay.toDateString()) tomorrowVal = val;
        if (d > today && d <= next7) weekSum += val;
        if (d > today && d <= next30) monthSum += val;
      }
      
      nextDayEl.textContent = tomorrowVal !== null ? Math.round(tomorrowVal) : "–";
      nextWeekEl.textContent = weekSum ? Math.round(weekSum) : "–";
      nextMonthEl.textContent = monthSum ? Math.round(monthSum) : "–";
      
      if (summary) {
        totalPredictionsEl.textContent = summary.total_predictions || "–";
      }
      
      const tStr = nextDay.getDate().toString().padStart(2, '0') + '/' + (nextDay.getMonth()+1).toString().padStart(2, '0') + '/' + nextDay.getFullYear();
      nextDayLabel.textContent = `Tomorrow (${tStr})`;
    }

    function sparseLabels(labels, maxTicks = 7) {
      const n = labels.length;
      if (n <= maxTicks) return labels.map((l,i) => ({label:l, show:true}));
      const step = Math.ceil(n/maxTicks);
      return labels.map((l,i) => ({label:l, show:(i%step)===0}));
    }

    function buildDatasets(prep) {
      const { labels, forecast, lower, upper, actual } = prep;
      const numericForecast = forecast.filter(v => v !== null && !isNaN(v));
      const med = median(numericForecast);
      const maxVal = numericForecast.length ? Math.max(...numericForecast) : null;
      const hasOutlier = med > 0 && maxVal && (maxVal/med > 10);
      const suggestedMax = hasOutlier ? Math.max(med*2, numericForecast[Math.floor(numericForecast.length*0.95)]*1.25) : undefined;

      const datasets = [];
      if (actual.some(v => v !== null)) {
        datasets.push({
          label: 'Actual',
          data: actual,
          borderColor: '#3498db',
          backgroundColor: 'rgba(52, 152, 219, 0.1)',
          tension: 0.2, 
          pointRadius: 3, 
          fill: false,
          borderWidth: 2
        });
      }
      datasets.push({
        label: 'Forecast',
        data: forecast,
        borderColor: '#27ae60',
        backgroundColor: 'rgba(39, 174, 96, 0.15)',
        tension: 0.25, 
        pointRadius: 4, 
        fill: true,
        borderWidth: 2
      });
      const hasCI = lower.some(x => x !== null) && upper.some(x => x !== null);
      if (hasCI) {
        datasets.push({
          label: 'Confidence Range',
          data: upper,
          borderColor: 'rgba(39, 174, 96, 0)',
          backgroundColor: 'rgba(39, 174, 96, 0.18)',
          fill: '-1', 
          pointRadius: 0, 
          tension: 0.25
        });
      }
      return { datasets, suggestedMax, hasOutlier };
    }

    function renderForecastHistory(history) {
      if (!history || !history.length) {
        forecastHistoryEl.innerHTML = '<div class="forecast-run-item">No forecast runs found</div>';
        return;
      }

      forecastHistoryEl.innerHTML = history.map(run => `
        <div class="forecast-run-item">
          <div>
            <strong>${run.run_type.charAt(0).toUpperCase() + run.run_type.slice(1)} Forecast</strong>
            <br>
            <small>Started: ${new Date(run.started_at).getDate().toString().padStart(2, '0')}/${(new Date(run.started_at).getMonth()+1).toString().padStart(2, '0')}/${new Date(run.started_at).getFullYear()} ${new Date(run.started_at).toLocaleTimeString()}</small>
            ${run.completed_at ? `<br><small>Duration: ${run.duration_display || 'N/A'}</small>` : ''}
          </div>
          <div>
            <span class="run-status status-${run.status}">${run.status.charAt(0).toUpperCase() + run.status.slice(1)}</span>
            ${run.predictions_created > 0 ? `<br><small>${run.predictions_created} predictions</small>` : ''}
          </div>
        </div>
      `).join('');
    }

    async function render(type) {
      metaEl.textContent = 'Loading…';
      const start = startInput.value || null;
      const end = endInput.value || null;
      
      try {
        const [rows, summary] = await Promise.all([
          fetchPred(type, start, end),
          fetchSummary(type)
        ]);
        
        
        if (!rows || !rows.length) {
          metaEl.textContent = 'No predictions available for selected range.';
          if (chart) { chart.destroy(); chart = null; }
          rangeLabel.textContent = '';
          return;
        }

        const prep = prepare(rows);
        updateSummary(prep, summary);

        // Auto-fill start/end fields + display visible range
        const firstDate = prep.labels[0];
        const lastDate = prep.labels[prep.labels.length - 1];
        if (!startInput.value) startInput.value = firstDate;
        if (!endInput.value) endInput.value = lastDate;
        const formatDate = (ds) => ds ? ds.split('-').reverse().join('/') : ds;
        rangeLabel.textContent = `📅 Showing predictions from ${formatDate(firstDate)} to ${formatDate(lastDate)}`;

        const { labels } = prep;
        const sparse = sparseLabels(labels, 7);
        const displayLabels = sparse.map(s => s.show ? formatDate(s.label) : '');
        const { datasets, suggestedMax, hasOutlier } = buildDatasets(prep);
        
        if (chart) chart.destroy();

        try {
          chart = new Chart(chartEl, {
            type: 'line',
            data: { labels: displayLabels, datasets },
          options: {
            responsive: true,
              maintainAspectRatio: false,
              interaction: { mode: 'nearest', intersect: false },
            plugins: {
              legend: {
                  position: 'top', 
                labels: {
                    color: '#34495e',
                    font: { size: 12 }
                  } 
                },
                tooltip: {
                  enabled: true,
                  intersect: false,
                  callbacks: {
                    title: ctx => `Date: ${ctx[0].label}`,
                    label: ctx => {
                      const v = ctx.raw;
                      return `${ctx.dataset.label}: ${Number(v).toLocaleString(undefined, {maximumFractionDigits:0})}`;
                    }
                  }
                },
                zoom: {
                  pan: { enabled: true, mode: 'x', modifierKey: 'ctrl' },
                  zoom: { wheel: {enabled: true}, pinch: {enabled: true}, mode: 'x' }
              }
            },
            scales: {
              x: {
                  ticks: { 
                    color: '#34495e', 
                    maxRotation: 0, 
                    autoSkip: false 
                  }, 
                  grid: { 
                    color: 'rgba(52, 73, 94, 0.1)' 
                  } 
              },
              y: {
                  ticks: { 
                    color: '#34495e' 
                  }, 
                  beginAtZero: true, 
                  suggestedMax,
                  grid: {
                    color: 'rgba(52, 73, 94, 0.1)'
                  }
                }
              },
              animation: { duration: 400 }
            }
          });
          
          console.log('Chart created successfully');
          metaEl.textContent = `${labels.length} data points loaded${hasOutlier ? ' • outliers detected' : ''}`;
        } catch (chartError) {
          console.error('Chart creation error:', chartError);
          metaEl.textContent = `Chart error: ${chartError.message}`;
          showAlert(`Chart creation failed: ${chartError.message}`, 'danger');
        }
      } catch (error) {
        metaEl.textContent = `Error loading data: ${error.message}`;
        showAlert(`Error loading predictions: ${error.message}`, 'danger');
      }
    }

    async function runForecast() {
      if (runForecastBtn.disabled) return;
      
      runForecastBtn.disabled = true;
      runForecastBtn.textContent = 'Running...';
      showProgress(true);
      updateProgress(10, 'Starting forecast...');
      
      try {
        const csrfToken = getCsrfToken();
        if (!csrfToken) {
          throw new Error('CSRF token not found. Please refresh the page and try again.');
        }
        
        const response = await fetch(API_ROOT + 'forecast-runs/trigger/', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
          },
          body: JSON.stringify({
            run_type: active,
            periods: 30
          })
        });
        
        if (!response.ok) {
           let errorMessage = `HTTP ${response.status}: ${response.statusText}`;
          try {
            const errorData = await response.json();
            if (errorData.error || errorData.detail) {
              errorMessage = errorData.error || errorData.detail || errorMessage;
            }
          } catch (e) {
            // If error response is not JSON, use status text
          }
          throw new Error(errorMessage);
        }
        
        currentForecastRun = await response.json();
        updateProgress(30, 'Forecast started, monitoring progress...');
        
        // Poll for completion
        const pollInterval = setInterval(async () => {
          try {
            const statusResponse = await fetch(API_ROOT + `forecast-runs/${currentForecastRun.id}/`);
            const statusData = await statusResponse.json();
            
            if (statusData.status === 'completed') {
              clearInterval(pollInterval);
              updateProgress(100, 'Forecast completed successfully!');
              showAlert(`Forecast completed! Created ${statusData.predictions_created} predictions.`, 'success');
              setTimeout(() => {
                showProgress(false);
                runForecastBtn.disabled = false;
                runForecastBtn.textContent = 'Run Forecast';
                render(active);
                loadForecastHistory();
              }, 2000);
            } else if (statusData.status === 'failed') {
              clearInterval(pollInterval);
              updateProgress(100, 'Forecast failed');
              showAlert(`Forecast failed: ${statusData.error_message || 'Unknown error'}`, 'danger');
              setTimeout(() => {
                showProgress(false);
                runForecastBtn.disabled = false;
                runForecastBtn.textContent = 'Run Forecast';
              }, 2000);
            } else {
              updateProgress(50, 'Forecast in progress...');
            }
          } catch (error) {
            clearInterval(pollInterval);
            updateProgress(100, 'Error monitoring forecast');
            showAlert(`Error monitoring forecast: ${error.message}`, 'danger');
            setTimeout(() => {
              showProgress(false);
              runForecastBtn.disabled = false;
              runForecastBtn.textContent = 'Run Forecast';
            }, 2000);
          }
        }, 2000);
        
      } catch (error) {
        showProgress(false);
        runForecastBtn.disabled = false;
        runForecastBtn.textContent = 'Run Forecast';
        showAlert(`Failed to start forecast: ${error.message}`, 'danger');
      }
    }

    async function exportCsv() {
      try {
        const start = startInput.value || null;
        const end = endInput.value || null;
        
        let url = API_ROOT + `predictions/export/?type=${encodeURIComponent(active)}`;
        if (start) url += `&start_date=${start}`;
        if (end) url += `&end_date=${end}`;
        
        const response = await fetch(url);
        if (!response.ok) throw new Error(`Export failed: ${response.statusText}`);
        
        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = `predictions_${active}_${new Date().toISOString().split('T')[0]}.csv`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(downloadUrl);
        
        showAlert('CSV export completed successfully!', 'success');
      } catch (error) {
        showAlert(`Export failed: ${error.message}`, 'danger');
      }
    }

    async function loadForecastHistory() {
      try {
        const history = await fetchForecastHistory();
        renderForecastHistory(history);
      } catch (error) {
        console.error('Failed to load forecast history:', error);
      }
    }

    // Event Listeners
    buttons.forEach(b => {
      b.addEventListener('click', e => {
        buttons.forEach(x => x.classList.remove('active'));
        e.currentTarget.classList.add('active');
        active = e.currentTarget.dataset.type;
        render(active);
      });
    });
    
    refreshBtn.addEventListener('click', () => render(active));
    runForecastBtn.addEventListener('click', runForecast);
    exportCsvBtn.addEventListener('click', exportCsv);
    applyBtn.addEventListener('click', () => render(active));
    clearBtn.addEventListener('click', () => {
      startInput.value = '';
      endInput.value = '';
      render(active);
    });

    // Initialize
    render(active);
    loadForecastHistory();
  })();