// tinytrack dashboard charts
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
  // Traffic chart
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
      data: ['Humans', 'Bots']
    },
    grid: { left: 40, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      data: data.timeLabels,
      axisLine: { lineStyle: { color: dark.border } },
      axisLabel: { color: dark.muted, rotate: 45 }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: dark.muted },
      splitLine: { lineStyle: { color: dark.border } }
    },
    series: [
      {
        name: 'Humans',
        type: 'line',
        smooth: true,
        data: data.humanValues,
        areaStyle: { opacity: 0.2 },
        lineStyle: { color: dark.accent },
        itemStyle: { color: dark.accent }
      },
      {
        name: 'Bots',
        type: 'line',
        smooth: true,
        data: data.botValues,
        areaStyle: { opacity: 0.1 },
        lineStyle: { color: dark.red },
        itemStyle: { color: dark.red }
      }
    ]
  });

  // Countries chart
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

  // Device chart
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
        { value: data.devices.desktop, name: 'Desktop', itemStyle: { color: dark.accent } },
        { value: data.devices.mobile, name: 'Mobile', itemStyle: { color: dark.green } },
        { value: data.devices.tablet, name: 'Tablet', itemStyle: { color: dark.muted } }
      ]
    }]
  });
}

function copySnippet() {
  const text = document.getElementById('snippet-text').innerText;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.querySelector('.copy-btn');
    btn.textContent = 'Copied!';
    btn.classList.add('copied');
    setTimeout(() => {
      btn.textContent = 'Copy';
      btn.classList.remove('copied');
    }, 2000);
  });
}

// Resize handler
window.addEventListener('resize', () => {
  document.querySelectorAll('[id$="-chart"]').forEach(el => {
    const chart = echarts.getInstanceByDom(el);
    if (chart) chart.resize();
  });
});
