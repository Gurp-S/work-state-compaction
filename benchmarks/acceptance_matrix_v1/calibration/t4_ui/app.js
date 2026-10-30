window.mountUsage = function(root, config, initial, load) {
  let current=initial, selected='', generation=0, stale=false, destroyed=false;
  const key=row=>JSON.stringify([row.provider,row.model]);
  const cost=row=>row.price_state==='unpriced'?'Unpriced':row.cost_cny===null?'Unknown':row.cost_cny.toFixed(2);
  function render(){
    root.replaceChildren();
    const el=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
    root.append(el('h1','Usage desk'));
    root.append(el('p','Filter scope: loaded rows only'));
    const section=el('section'), label=el('label','Model '), select=el('select');
    select.setAttribute('aria-label','Model');
    const all=el('option','All models');all.value='';select.append(all);
    const rows=current.kind==='ready'?current.rows:[];
    const pairs=new Map(rows.map(row=>[key(row),row]));
    for(const [value,row] of pairs){const option=el('option',row.provider+' / '+row.model);option.value=value;select.append(option);}
    if(selected&&!pairs.has(selected))selected='';
    select.value=selected;select.onchange=()=>{selected=select.value;render();};label.append(select);section.append(label);
    const refresh=el('button','Refresh');
    refresh.onclick=async()=>{const own=++generation;try{const next=await load();if(!destroyed&&own===generation){current=next;stale=false;render();}}catch(error){if(!destroyed&&own===generation){stale=true;render();}}};
    section.append(refresh);root.append(section);
    const visible=rows.filter(row=>!selected||key(row)===selected);
    const status=el('p',stale?'Stale: refresh failed':current.kind==='missing'?'Data unavailable':visible.length?'Ready':'No matching rows');
    status.setAttribute('role','status');root.append(status);
    const table=el('table'), head=el('thead'), hr=el('tr');
    for(const name of ['Provider / model','Tokens','Cost CNY'])hr.append(el('th',name));head.append(hr);table.append(head);
    const body=el('tbody');
    for(const row of visible){const tr=el('tr');tr.dataset.rowId=row.id;tr.append(el('td',row.provider+' / '+row.model),el('td',row.tokens===null?'Unknown':String(row.tokens)),el('td',cost(row)));body.append(tr);}
    table.append(body);root.append(table);
    const total=el('output',visible.some(row=>row.cost_cny===null)?'Incomplete':visible.reduce((s,row)=>s+row.cost_cny,0).toFixed(2));
    total.setAttribute('aria-label','Cost total');root.append(total);
  }
  render();
  return {destroy(){destroyed=true;generation++;root.replaceChildren();}};
};
