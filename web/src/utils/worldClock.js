export function narrativePeriod(date, timeZone = undefined) {
  const options = {
    hour: '2-digit',
    hourCycle: 'h23',
  };
  if (timeZone) options.timeZone = timeZone;

  const hourPart = new Intl.DateTimeFormat('zh-CN', options)
    .formatToParts(date)
    .find(part => part.type === 'hour');
  const parsedHour = Number(hourPart?.value);
  const hour = Number.isFinite(parsedHour) ? parsedHour : date.getHours();

  if (hour >= 5 && hour < 8) return '清晨';
  if (hour >= 8 && hour < 12) return '上午';
  if (hour >= 12 && hour < 14) return '中午';
  if (hour >= 14 && hour < 18) return '下午';
  if (hour >= 18 && hour < 22) return '傍晚';
  return '深夜';
}
