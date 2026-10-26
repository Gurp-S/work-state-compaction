async function refresh() {
  const notice = document.querySelector('#notice'); notice.textContent = '正在读取';
  try {
    const response = await fetch('/api/bookings');
    if (!response.ok) throw new Error('读取失败 ' + response.status);
    const body = await response.json();
    document.querySelector('#records').replaceChildren(...body.items.map(item => {
      const article = document.createElement('article');
      const title = document.createElement('h2'); title.textContent = item.name || item.customer || item.resource_id;
      const details = document.createElement('pre'); details.textContent = JSON.stringify(item, null, 2);
      article.append(title, details); return article;
    })); notice.textContent = body.items.length + ' 条记录';
  } catch (error) { notice.textContent = error.message; }
}
document.querySelector('#refresh').addEventListener('click', refresh);
refresh();
