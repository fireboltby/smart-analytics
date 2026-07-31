// smart-analytics 仪表盘图表
const dark = {
  bg: '#0d1117',
  card: '#161b22',
  border: '#30363d',
  text: '#c9d1d9',
  muted: '#8b949e',
  accent: '#58a6ff',
  green: '#3fb950',
  red: '#f85149'
};

function initCharts(data) {
  // 访问趋势图表
  echarts.init(document.getElementById('traffic-chart')).setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: dark.card,
      borderColor: dark.border,
      textStyle: { color: dark.text }
    },
    legend: {
      bottom: 0,
      textStyle: { color: dark.muted },
      data: ['真人', '机器人']
    },
    grid: { left: 40, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      data: data.timeLabels,
      axisLine: { lineStyle: { color: dark.border } },
      axisLabel: { color: dark.muted, rotate: 45, hideOverlap: true }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: dark.muted },
      splitLine: { lineStyle: { color: dark.border } }
    },
    series: [
      {
        name: '真人',
        type: 'line',
        smooth: true,
        data: data.humanValues,
        areaStyle: { opacity: 0.2 },
        lineStyle: { color: dark.accent },
        itemStyle: { color: dark.accent }
      },
      {
        name: '机器人',
        type: 'line',
        smooth: true,
        data: data.botValues,
        areaStyle: { opacity: 0.1 },
        lineStyle: { color: dark.red },
        itemStyle: { color: dark.red }
      }
    ]
  });

  // 国家/地区图表
  echarts.init(document.getElementById('geo-chart')).setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: dark.card,
      borderColor: dark.border,
      textStyle: { color: dark.text }
    },
    grid: { left: 100, right: 20, top: 10, bottom: 10 },
    xAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: dark.muted },
      splitLine: { lineStyle: { color: dark.border } }
    },
    yAxis: {
      type: 'category',
      data: data.countryLabels.slice().reverse(),
      axisLine: { show: false },
      axisLabel: { color: dark.muted }
    },
    series: [{
      type: 'bar',
      data: data.countryValues.slice().reverse(),
      itemStyle: { color: dark.green, borderRadius: [0, 4, 4, 0] }
    }]
  });

  // 设备分布图表
  echarts.init(document.getElementById('device-chart')).setOption({
    tooltip: {
      trigger: 'item',
      backgroundColor: dark.card,
      borderColor: dark.border,
      textStyle: { color: dark.text }
    },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 6, borderColor: dark.bg, borderWidth: 2 },
      label: { show: true, position: 'outside', color: dark.muted, formatter: '{b}\n{c}' },
      data: [
        { value: data.devices.desktop, name: '桌面端', itemStyle: { color: dark.accent } },
        { value: data.devices.mobile, name: '移动端', itemStyle: { color: dark.green } },
        { value: data.devices.tablet, name: '平板', itemStyle: { color: dark.muted } }
      ]
    }]
  });

  // 新/老访客环形图
  const totalVR = (data.newVisitors || 0) + (data.returningVisitors || 0);
  echarts.init(document.getElementById('visitor-chart')).setOption({
    tooltip: {
      trigger: 'item',
      backgroundColor: dark.card,
      borderColor: dark.border,
      textStyle: { color: dark.text },
      formatter: '{b}: {c} ({d}%)'
    },
    legend: {
      bottom: 0,
      textStyle: { color: dark.muted },
      data: ['新访客', '老访客']
    },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '45%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 6, borderColor: dark.bg, borderWidth: 2 },
      label: { show: true, position: 'outside', color: dark.muted, formatter: '{b}\n{c}' },
      data: [
        { value: data.newVisitors || 0, name: '新访客', itemStyle: { color: dark.accent } },
        { value: data.returningVisitors || 0, name: '老访客', itemStyle: { color: dark.green } }
      ]
    }]
  });
  if (totalVR === 0) {
    const el = document.getElementById('visitor-chart');
    if (el) el.innerHTML = '<p class="empty" style="padding:30px 0;text-align:center">暂无数据</p>';
  }

  // 访问时段分布（24h）
  echarts.init(document.getElementById('hour-chart')).setOption({
    tooltip: { trigger: 'axis', backgroundColor: dark.card, borderColor: dark.border, textStyle: { color: dark.text } },
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: data.hourLabels, axisLine: { lineStyle: { color: dark.border } }, axisLabel: { color: dark.muted, interval: 1, rotate: 45 } },
    yAxis: { type: 'value', axisLine: { show: false }, axisLabel: { color: dark.muted }, splitLine: { lineStyle: { color: dark.border } } },
    series: [{ type: 'bar', data: data.hourValues, itemStyle: { color: dark.accent, borderRadius: [3, 3, 0, 0] } }]
  });

  // 星期分布
  echarts.init(document.getElementById('weekday-chart')).setOption({
    tooltip: { trigger: 'axis', backgroundColor: dark.card, borderColor: dark.border, textStyle: { color: dark.text } },
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: data.weekdayLabels, axisLine: { lineStyle: { color: dark.border } }, axisLabel: { color: dark.muted } },
    yAxis: { type: 'value', axisLine: { show: false }, axisLabel: { color: dark.muted }, splitLine: { lineStyle: { color: dark.border } } },
    series: [{ type: 'bar', data: data.weekdayValues, itemStyle: { color: dark.green, borderRadius: [3, 3, 0, 0] } }]
  });
}

function copySnippet() {
  const text = document.getElementById('snippet-text').innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.querySelector('.copy-btn');
    btn.textContent = '已复制！';
    btn.classList.add('copied');
    setTimeout(() => {
      btn.textContent = '复制';
      btn.classList.remove('copied');
    }, 2000);
  });
}

// 窗口缩放时重绘图表
window.addEventListener('resize', () => {
  document.querySelectorAll('[id$="-chart"]').forEach(el => {
    const chart = echarts.getInstanceByDom(el);
    if (chart) chart.resize();
  });
});

// 实时在线人数轮询（按当前站点隔离）
function startRealtime() {
  const el = document.getElementById('realtime-count');
  if (!el) return;
  const site = el.dataset.site || '';
  async function tick() {
    try {
      const res = await fetch('/api/realtime?site=' + encodeURIComponent(site));
      if (res.ok) {
        const d = await res.json();
        el.textContent = (d.online || 0).toLocaleString();
      }
    } catch (e) {}
  }
  tick();
  setInterval(tick, 10000);
}
startRealtime();
