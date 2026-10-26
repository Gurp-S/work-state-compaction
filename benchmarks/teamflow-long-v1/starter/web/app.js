const project = document.querySelector('#project-select');
const notice = document.querySelector('#notice');
async function request(path, options = {}) {
  const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'Request failed');
  return body;
}
async function refresh() {
  const data = await request('/api/issues?project_id=' + encodeURIComponent(project.value));
  document.querySelector('#issues').replaceChildren(...data.items.map(issue => {
    const article = document.createElement('article');
    article.dataset.testid = 'issue-card'; article.dataset.issueId = issue.id;
    const title = document.createElement('h2'); title.textContent = issue.title;
    const state = document.createElement('p'); state.textContent = issue.status;
    article.append(title, state); return article;
  }));
}
document.querySelector('#create-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    await request('/api/issues', {method: 'POST', body: JSON.stringify({project_id: project.value, title: document.querySelector('#issue-title').value})});
    document.querySelector('#issue-title').value = ''; await refresh(); notice.textContent = 'Created';
  } catch (error) { notice.textContent = error.message; }
});
project.addEventListener('change', refresh);
try {
  const data = await request('/api/projects');
  for (const item of data.items) { const option = new Option(item.name, item.id); project.add(option); }
  await refresh();
} catch (error) { notice.textContent = error.message; }
