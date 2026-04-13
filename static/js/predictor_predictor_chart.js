(function(){
    const API_ROOT = "/predictor/api/predictions/?type=";
    const chartEl = document.getElementById("predChart");
    const metaEl = document.getElementById("meta");
    const rangeLabel = document.getElementById("range-label");
    const buttons = document.querySelectorAll(".btn[data-type]");
    const refreshBtn = document.getElementById("refresh");
    const startInput = document.getElementById("start-date");
    const endInput = document.getElementById("end-date");
    const applyBtn = document.getElementById("apply");
    const clearBtn = document.getElementById("clear");
    const nextDayEl = document.getElementById("next-day");
    const nextDayLabel = document.getElementById("next-day-label");
    const nextWeekEl = document.getElementById("next-week");
    const nextMonthEl = document.getElementById("next-month");
    let active = "daily";
    let chart = null;

    const toNum = v => (v === null || v === undefined) ? null : Number(v);
    const median = arr => { if(!arr.length) return 0; const s = arr.slice().sort((a,b)=>a-b); const m = Math.floor(s.length/2); return s.length%2 ? s[m] : (s[m-1]+s[m])/2; };

    async function fetchPred(type,start,end){
      let url = API_ROOT + encodeURIComponent(type);
      const params=[];
      if(start) params.push("start="+start);
      if(end) params.push("end="+end);
      if(params.length) url+="&"+params.join("&");
      else url+="&upcoming=1";
      const r = await fetch(url);
      if(!r.ok) throw new Error("API "+r.status);
      return await r.json();
    }

    function prepare(rows){
      rows.sort((a,b)=> new Date(a.date) - new Date(b.date));
      const labels=[],forecast=[],lower=[],upper=[],actual=[];
      for(const r of rows){
        labels.push(r.date);
        forecast.push(toNum(r.predicted_value));
        lower.push(toNum(r.yhat_lower));
        upper.push(toNum(r.yhat_upper));
        actual.push(toNum(r.actual_value));
      }
      return { labels,forecast,lower,upper,actual };
    }

    function updateSummary(prep){
      const { labels,forecast } = prep;
      const today=new Date();
      const nextDay=new Date(today); nextDay.setDate(today.getDate()+1);
      const next7=new Date(today); next7.setDate(today.getDate()+7);
      const next30=new Date(today); next30.setDate(today.getDate()+30);
      let tomorrowVal=null,weekSum=0,monthSum=0;
      for(let i=0;i<labels.length;i++){
        const d=new Date(labels[i]);
        const val=forecast[i]||0;
        if(d.toDateString()===nextDay.toDateString()) tomorrowVal=val;
        if(d>today&&d<=next7) weekSum+=val;
        if(d>today&&d<=next30) monthSum+=val;
      }
      nextDayEl.textContent=tomorrowVal!==null?Math.round(tomorrowVal):"–";
      nextWeekEl.textContent=weekSum?Math.round(weekSum):"–";
      nextMonthEl.textContent=monthSum?Math.round(monthSum):"–";
      const tStr = nextDay.getDate().toString().padStart(2, '0') + '/' + (nextDay.getMonth()+1).toString().padStart(2, '0') + '/' + nextDay.getFullYear();
      nextDayLabel.textContent=`Tomorrow (${tStr})`;
    }

    function sparseLabels(labels,maxTicks=7){
      const n=labels.length;
      if(n<=maxTicks) return labels.map((l,i)=>({label:l,show:true}));
      const step=Math.ceil(n/maxTicks);
      return labels.map((l,i)=>({label:l,show:(i%step)===0}));
    }

    function buildDatasets(prep){
      const { labels,forecast,lower,upper,actual }=prep;
      const numericForecast=forecast.filter(v=>v!==null&&!isNaN(v));
      const med=median(numericForecast);
      const maxVal=numericForecast.length?Math.max(...numericForecast):null;
      const hasOutlier=med>0&&maxVal&&(maxVal/med>10);
      const suggestedMax=hasOutlier?Math.max(med*2,numericForecast[Math.floor(numericForecast.length*0.95)]*1.25):undefined;

      const datasets=[];
      if(actual.some(v=>v!==null)){
        datasets.push({
          label:'Actual',
          data:actual,
          borderColor:'#3498db',
          backgroundColor:'rgba(52, 152, 219, 0.1)',
          tension:0.2, 
          pointRadius:3, 
          fill:false,
          borderWidth: 2
        });
      }
      datasets.push({
        label:'Forecast',
        data:forecast,
        borderColor:'#27ae60',
        backgroundColor:'rgba(39, 174, 96, 0.15)',
        tension:0.25, 
        pointRadius:4, 
        fill:true,
        borderWidth: 2
      });
      const hasCI=lower.some(x=>x!==null)&&upper.some(x=>x!==null);
      if(hasCI){
        datasets.push({
          label:'Confidence Range',
          data:upper,
          borderColor:'rgba(39, 174, 96, 0)',
          backgroundColor:'rgba(39, 174, 96, 0.18)',
          fill:'-1', 
          pointRadius:0, 
          tension:0.25
        });
      }
      return { datasets,suggestedMax,hasOutlier };
    }

    async function render(type){
      metaEl.textContent='Loading…';
      const start=startInput.value||null;
      const end=endInput.value||null;
      const rows=await fetchPred(type,start,end);
      if(!rows||!rows.length){
        metaEl.textContent='No predictions available for selected range.';
        if(chart){ chart.destroy(); chart=null; }
        rangeLabel.textContent='';
        return;
      }

      const prep=prepare(rows);
      updateSummary(prep);

      // Auto-fill start/end fields + display visible range
      const firstDate=prep.labels[0];
      const lastDate=prep.labels[prep.labels.length-1];
      if(!startInput.value) startInput.value=firstDate;
      if(!endInput.value) endInput.value=lastDate;
      const formatDate = (ds) => ds ? ds.split('-').reverse().join('/') : ds;
      rangeLabel.textContent=`📅 Showing predictions from ${formatDate(firstDate)} to ${formatDate(lastDate)}`;

      const { labels }=prep;
      const sparse=sparseLabels(labels,7);
      const displayLabels=sparse.map(s=>s.show?formatDate(s.label):'');
      const { datasets,suggestedMax,hasOutlier }=buildDatasets(prep);
      if(chart) chart.destroy();

      chart=new Chart(chartEl,{
        type:'line',
        data:{ labels:displayLabels, datasets },
        options:{
          responsive:true,
          maintainAspectRatio:false,
          interaction:{ mode:'nearest', intersect:false },
          plugins:{
            legend:{ 
              position:'top', 
              labels:{ 
                color:'#34495e',
                font: { size: 12 }
              } 
            },
            tooltip:{
              enabled:true,
              intersect:false,
              callbacks:{
                title:ctx=>`Date: ${ctx[0].label}`,
                label:ctx=>{
                  const v=ctx.raw;
                  return `${ctx.dataset.label}: ${Number(v).toLocaleString(undefined,{maximumFractionDigits:0})}`;
                }
              }
            },
            zoom:{
              pan:{ enabled:true, mode:'x', modifierKey:'ctrl' },
              zoom:{ wheel:{enabled:true}, pinch:{enabled:true}, mode:'x' }
            }
          },
          scales:{
            x:{ 
              ticks:{ 
                color:'#34495e', 
                maxRotation:0, 
                autoSkip:false 
              }, 
              grid:{ 
                color:'rgba(52, 73, 94, 0.1)' 
              } 
            },
            y:{ 
              ticks:{ 
                color:'#34495e' 
              }, 
              beginAtZero:true, 
              suggestedMax,
              grid: {
                color: 'rgba(52, 73, 94, 0.1)'
              }
            }
          },
          animation:{ duration:400 }
        }
      });

      metaEl.textContent=`${labels.length} data points loaded${hasOutlier?' • outliers detected':''}`;
    }

    // Event Listeners
    buttons.forEach(b=>{
      b.addEventListener('click',e=>{
        buttons.forEach(x=>x.classList.remove('active'));
        e.currentTarget.classList.add('active');
        active=e.currentTarget.dataset.type;
        render(active);
      });
    });
    refreshBtn.addEventListener('click',()=>render(active));
    applyBtn.addEventListener('click',()=>render(active));
    clearBtn.addEventListener('click',()=>{
      startInput.value='';
      endInput.value='';
      render(active);
    });

    // Initialize
    render(active);
  })();