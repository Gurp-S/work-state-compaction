window.mountUsage = function(root, config, initial, load) {
  root.innerHTML='<h1>Usage desk</h1><label>Model <select aria-label="Model"><option>All</option></select></label><p role="status">Ready</p><table><tbody></tbody></table><button>Refresh</button>';
  root.querySelector('tbody').textContent = JSON.stringify(initial.rows || []);
  return {destroy(){root.replaceChildren();}};
};
