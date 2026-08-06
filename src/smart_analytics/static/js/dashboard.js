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

// 浅色（普通模式）调色板，与 CSS [data-theme="light"] 变量保持一致
const light = {
  bg: '#f6f8fa',
  card: '#ffffff',
  border: '#d0d7de',
  text: '#1f2328',
  muted: '#656d76',
  accent: '#0969da',
  green: '#1a7f37',
  red: '#cf222e'
};

// 安全初始化：先 dispose 已存在的实例，避免二次 init 报错（换肤重绘时复用同一 DOM）
function chart(id) {
  const el = document.getElementById(id);
  if (!el) return null;
  // 容器尺寸为 0 时 echarts.init 会拿到 0×0 画布，后续 resize 也难恢复；先防御
  const rect = el.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return null;
  try {
    const ex = echarts.getInstanceByDom(el);
    if (ex) ex.dispose();
  } catch (e) {}
  try {
    const inst = echarts.init(el);
    // 某些浏览器（尤其移动端 WebKit）init 时布局未稳定，立刻 resize 一次校正
    inst.resize();
    return inst;
  } catch (e) { return null; }
}

let __dashData = null;

// 实际的图表初始化逻辑（在布局稳定后调用）
function __initChartsImpl(data) {
  const c = document.documentElement.getAttribute('data-theme') === 'light' ? light : dark;
  // 注意：以下所有图表配色均使用 c.（随 data-theme 在 light/dark 间切换）
  // 访问趋势图表
  chart('traffic-chart').setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.card,
      borderColor: c.border,
      textStyle: { color: c.text }
    },
    legend: {
      bottom: 0,
      textStyle: { color: c.muted },
      data: ['真人', '机器人']
    },
    grid: { left: 40, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      data: data.timeLabels,
      axisLine: { lineStyle: { color: c.border } },
      axisLabel: { color: c.muted, rotate: 45, hideOverlap: true }
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: c.muted },
      splitLine: { lineStyle: { color: c.border } }
    },
    series: [
      {
        name: '真人',
        type: 'line',
        smooth: true,
        data: data.humanValues,
        areaStyle: { opacity: 0.2 },
        lineStyle: { color: c.accent },
        itemStyle: { color: c.accent }
      },
      {
        name: '机器人',
        type: 'line',
        smooth: true,
        data: data.botValues,
        areaStyle: { opacity: 0.1 },
        lineStyle: { color: c.red },
        itemStyle: { color: c.red }
      }
    ]
  });

  // 国家/地区图表
  chart('geo-chart').setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.card,
      borderColor: c.border,
      textStyle: { color: c.text }
    },
    grid: { left: 100, right: 20, top: 10, bottom: 10 },
    xAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: c.muted },
      splitLine: { lineStyle: { color: c.border } }
    },
    yAxis: {
      type: 'category',
      data: data.countryLabels.slice().reverse(),
      axisLine: { show: false },
      axisLabel: { color: c.muted }
    },
    series: [{
      type: 'bar',
      data: data.countryValues.slice().reverse(),
      itemStyle: { color: c.green, borderRadius: [0, 4, 4, 0] }
    }]
  });

  // 省份分布图表
  chart('region-chart').setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.card,
      borderColor: c.border,
      textStyle: { color: c.text }
    },
    grid: { left: 100, right: 20, top: 10, bottom: 10 },
    xAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: c.muted },
      splitLine: { lineStyle: { color: c.border } }
    },
    yAxis: {
      type: 'category',
      data: data.regionLabels.slice().reverse(),
      axisLine: { show: false },
      axisLabel: { color: c.muted }
    },
    series: [{
      type: 'bar',
      data: data.regionValues.slice().reverse(),
      itemStyle: { color: c.accent, borderRadius: [0, 4, 4, 0] }
    }]
  });

  // 城市分布图表
  chart('city-chart').setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: c.card,
      borderColor: c.border,
      textStyle: { color: c.text }
    },
    grid: { left: 100, right: 20, top: 10, bottom: 10 },
    xAxis: {
      type: 'value',
      axisLine: { show: false },
      axisLabel: { color: c.muted },
      splitLine: { lineStyle: { color: c.border } }
    },
    yAxis: {
      type: 'category',
      data: data.cityLabels.slice().reverse(),
      axisLine: { show: false },
      axisLabel: { color: c.muted }
    },
    series: [{
      type: 'bar',
      data: data.cityValues.slice().reverse(),
      itemStyle: { color: c.green, borderRadius: [0, 4, 4, 0] }
    }]
  });

  // 设备分布图表
  chart('device-chart').setOption({
    tooltip: {
      trigger: 'item',
      backgroundColor: c.card,
      borderColor: c.border,
      textStyle: { color: c.text }
    },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '50%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 6, borderColor: c.bg, borderWidth: 2 },
      label: { show: true, position: 'outside', color: c.muted, formatter: '{b}\n{c}' },
      data: [
        { value: data.devices.desktop, name: '桌面端', itemStyle: { color: c.accent } },
        { value: data.devices.mobile, name: '移动端', itemStyle: { color: c.green } },
        { value: data.devices.tablet, name: '平板', itemStyle: { color: c.muted } }
      ]
    }]
  });

  // 新/老访客环形图
  const totalVR = (data.newVisitors || 0) + (data.returningVisitors || 0);
  chart('visitor-chart').setOption({
    tooltip: {
      trigger: 'item',
      backgroundColor: c.card,
      borderColor: c.border,
      textStyle: { color: c.text },
      formatter: '{b}: {c} ({d}%)'
    },
    legend: {
      bottom: 0,
      textStyle: { color: c.muted },
      data: ['新访客', '老访客']
    },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '45%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 6, borderColor: c.bg, borderWidth: 2 },
      label: { show: true, position: 'outside', color: c.muted, formatter: '{b}\n{c}' },
      data: [
        { value: data.newVisitors || 0, name: '新访客', itemStyle: { color: c.accent } },
        { value: data.returningVisitors || 0, name: '老访客', itemStyle: { color: c.green } }
      ]
    }]
  });
  if (totalVR === 0) {
    const el = document.getElementById('visitor-chart');
    if (el) el.innerHTML = '<p class="empty" style="padding:30px 0;text-align:center">暂无数据</p>';
  }

  // 访问时段分布（24h）
  chart('hour-chart').setOption({
    tooltip: { trigger: 'axis', backgroundColor: c.card, borderColor: c.border, textStyle: { color: c.text } },
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: data.hourLabels, axisLine: { lineStyle: { color: c.border } }, axisLabel: { color: c.muted, interval: 1, rotate: 45 } },
    yAxis: { type: 'value', axisLine: { show: false }, axisLabel: { color: c.muted }, splitLine: { lineStyle: { color: c.border } } },
    series: [{ type: 'bar', data: data.hourValues, itemStyle: { color: c.accent, borderRadius: [3, 3, 0, 0] } }]
  });

  // 星期分布
  chart('weekday-chart').setOption({
    tooltip: { trigger: 'axis', backgroundColor: c.card, borderColor: c.border, textStyle: { color: c.text } },
    grid: { left: 40, right: 20, top: 20, bottom: 30 },
    xAxis: { type: 'category', data: data.weekdayLabels, axisLine: { lineStyle: { color: c.border } }, axisLabel: { color: c.muted } },
    yAxis: { type: 'value', axisLine: { show: false }, axisLabel: { color: c.muted }, splitLine: { lineStyle: { color: c.border } } },
    series: [{ type: 'bar', data: data.weekdayValues, itemStyle: { color: c.green, borderRadius: [3, 3, 0, 0] } }]
  });
}

function initCharts(data) {
  __dashData = data;
  // 移动端 Safari/WebKit 在首帧常拿不到真实容器尺寸，用 setTimeout 让布局充分回流
  setTimeout(() => {
    __initChartsImpl(data);
    // 多轮校正：首帧、50ms、250ms，覆盖横竖屏/抽屉展开等延迟场景
    __resizeAllCharts();
    setTimeout(__resizeAllCharts, 50);
    setTimeout(__resizeAllCharts, 250);
  }, 0);
}

// 供主题切换按钮调用：用最新数据重绘全部图表（换肤时同步图表配色）
window.__rerenderCharts = function () {
  if (__dashData) initCharts(__dashData);
};

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

// 窗口缩放 / 横竖屏切换时重绘图表（rAF 节流 + 二次校正，杜绝塌缩错位）
let __resizeChartsRAF = null;
function __resizeAllCharts() {
  document.querySelectorAll('[id$="-chart"]').forEach(el => {
    const inst = echarts.getInstanceByDom(el);
    if (inst) inst.resize();
  });
}
function __scheduleChartResize() {
  if (__resizeChartsRAF) cancelAnimationFrame(__resizeChartsRAF);
  __resizeChartsRAF = requestAnimationFrame(() => {
    __resizeAllCharts();
    // 布局回流后再校正一次，避免响应式断点切换瞬间图表尺寸计算偏差
    requestAnimationFrame(__resizeAllCharts);
  });
}
window.addEventListener('resize', __scheduleChartResize);
window.addEventListener('orientationchange', () => {
  setTimeout(__resizeAllCharts, 250);
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
