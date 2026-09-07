'use strict';
const $ = (s) => document.querySelector(s);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = value => new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 0}).format(value);
const money = value => value == null ? '—' : `${number(value)} $`;
const date = value => value ? new Date(value).toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}) : 'Ещё не было';
const risk = value => value == null ? {label:'Не рассчитан',className:''} : value <= 25 ? {label:'Низкий',className:''} : value <= 50 ? {label:'Средний',className:'medium'} : {label:'Высокий',className:'high'};
let toastTimer;
function notify(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 7000); }
async function api(path, options={}) {
  const response = await fetch(path, {headers: {'Content-Type':'application/json'}, ...options});
  let data;
  try { data = await response.json(); } catch { throw new Error('Сервер вернул неожиданный ответ. Попробуйте ещё раз.'); }
  if (!response.ok) {
    const detail = Array.isArray(data.detail) ? 'Проверьте значения и границы фильтров / расходов.' : data.detail;
    throw new Error(detail || 'Не удалось выполнить запрос.');
  }
  return data;
}
function original(item) { return item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">Оригинал ↗</a>` : '<span class="muted">Учебное объявление</span>'; }
function photo(item) {
  return item.photos.length ? `<img src="${esc(item.photos[0])}" alt="${item.source === 'mock' ? 'Пример модели из Wikimedia Commons' : esc(item.title)}" loading="lazy" referrerpolicy="no-referrer">` : '<div class="photo-empty">Фотографии нет</div>';
}
function card(item) {
  const s = item.score, r = risk(s?.risk_score);
  const discount = s?.discount_percent;
  return `<article class="card"><a class="card-photo" href="/listings/${item.id}" aria-label="Открыть ${esc(item.title)}">${photo(item)}
    <span class="card-score">${s?.total_score == null ? '—' : number(s.total_score)} <small>/ 100</small></span>
    ${item.source === 'mock' ? '<span class="image-caption">ДЕМО · фото для иллюстрации</span>' : ''}</a>
    <div class="card-content"><div class="card-title"><h3><a href="/listings/${item.id}">${esc(item.title)}</a></h3></div>
    <p class="spec-line">${item.year} &nbsp;·&nbsp; ${item.mileage_km == null ? 'Пробег не указан' : number(item.mileage_km)+' км'}</p>
    <p class="spec-line">${esc(item.fuel_type || 'Топливо не указано')} · ${esc(item.transmission || 'Коробка не указана')}</p>
    <p class="spec-line">⌖ ${esc(item.city || 'Город не указан')}</p>
    <div class="price-row"><strong>${money(item.price_usd)}</strong>${discount != null ? `<span class="discount ${discount < 0 ? 'over' : ''}">${number(Math.abs(discount))}% ${discount < 0 ? 'выше' : 'ниже'} рынка</span>` : ''}</div>
    <div class="market-row">${s?.estimated_market_price == null ? 'Недостаточно данных для оценки' : `Оценка рынка ${money(s.estimated_market_price)}`}</div>
    <div class="profit-row"><span>Потенциальная прибыль</span><strong class="${s?.potential_profit < 0 ? 'negative' : ''}">${money(s?.potential_profit)}</strong></div>
    <div class="confidence-line">${s?.explanation.comparable_count || 0} аналогов · ${item.photos.length} фото</div><div class="card-bottom"><span class="risk ${r.className}">● ${r.label} риск</span>${original(item)}</div></div></article>`;
}
let modelsByBrand = {}, allModels = [];
let page = 1, requestId = 0, importing = false, initialFiltersApplied = false;
function searchParams() {
  const params = new URLSearchParams();
  for (const [key, value] of new FormData($('#filters'))) if (String(value).trim()) params.set(key, String(value).trim());
  params.set('sort', $('#sort').value); params.set('page', String(page));
  return params;
}
async function loadList() {
  const current = ++requestId;
  $('#listings').setAttribute('aria-busy','true');
  try {
    const params = searchParams();
    const result = await api(`/api/listings?${params}`);
    if (current !== requestId) return;
    $('#listings').innerHTML = result.items.length ? result.items.map(card).join('') : '<div class="empty"><strong>Пока нет подходящих автомобилей</strong>Измените фильтры или обновите объявления.</div>';
    $('#result-count').textContent = `${number(result.total)} объявлений в выборке`;
    $('#page-label').textContent = `Страница ${page} из ${Math.max(1, Math.ceil(result.total/result.page_size))}`;
    $('#prev-page').disabled = page <= 1; $('#next-page').disabled = page * result.page_size >= result.total;
    renderActiveFilters(params);
    history.replaceState(null,'',`/?${params}`);
  } catch (error) { if (current === requestId) { $('#listings').innerHTML = `<div class="empty error">${esc(error.message)}</div>`; $('#result-count').textContent = 'Не удалось загрузить результаты'; } }
  finally { if (current === requestId) $('#listings').setAttribute('aria-busy','false'); }
}
async function loadStats() {
  const stats = await api('/api/stats');
  $('#stat-active').textContent = number(stats.active); $('#stat-new').textContent = number(stats.new_today);
  $('#stat-deals').textContent = number(stats.potential_deals); $('#stat-time').textContent = date(stats.last_updated);
  $('#stat-interval').textContent = stats.import_running ? 'Выполняется обновление…' : `Интервал: ${number(stats.interval_minutes/60)} ч`;
  $('#import-button').disabled = stats.import_running || importing;
  const notes = stats.last_import?.status === 'failed' ? [stats.last_import.details.error] : stats.last_import?.details.warnings || [];
  $('#import-note').hidden = !notes.length; $('#import-note').textContent = notes.join(' ');
  modelsByBrand = stats.models_by_brand || {}; allModels = stats.facets.model;
  document.querySelectorAll('[data-facet]').forEach(select => {
    const value = select.value, label = select.options[0].text;
    select.innerHTML = `<option value="">${esc(label)}</option>` + stats.facets[select.dataset.facet].map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
    select.value = value;
  });
  $('#locations').innerHTML = [...new Set([...stats.facets.city,...stats.facets.region])].map(v => `<option value="${esc(v)}"></option>`).join('');
  if (!initialFiltersApplied) {
    const params = new URLSearchParams(location.search);
    for (const [key,value] of params) { const input = $('#filters').elements.namedItem(key); if(input) input.value = value; }
    $('#sort').value = ['score','price','date','profit'].includes(params.get('sort')) ? params.get('sort') : 'score';
    page = Math.max(1, parseInt(params.get('page')) || 1); initialFiltersApplied = true;
  }
  syncModels();
  return stats;
}
function syncModels() {
  const brand = $('#filters').elements.brand.value;
  const model = $('#filters').elements.model;
  const selected = model.value;
  const choices = brand ? modelsByBrand[brand] || [] : allModels;
  model.innerHTML = '<option value="">Все модели</option>' + choices.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
  model.value = choices.includes(selected) ? selected : '';
}
const filterLabels = {q:'Поиск',brand:'Марка',model:'Модель',year_from:'Год от',year_to:'Год до',price_from:'Цена от',price_to:'Цена до',mileage_max:'Пробег до',location:'Место',fuel_type:'Топливо',transmission:'Коробка',discount_min:'Скидка от, %',profit_min:'Прибыль от',risk_max:'Риск до'};
function renderActiveFilters(params) {
  $('#active-filters').innerHTML = [...params].filter(([key])=>filterLabels[key]).map(([key,value])=>`<button type="button" data-remove-filter="${key}" aria-label="Убрать фильтр ${esc(filterLabels[key])}">${esc(filterLabels[key])}: ${esc(value)} ×</button>`).join('');
}
function clearPreset() { document.querySelectorAll('[data-preset]').forEach(b=>b.setAttribute('aria-pressed','false')); }
async function initCatalog() {
  $('#filters').elements.brand.addEventListener('change', syncModels);
  $('#filters').addEventListener('input', clearPreset);
  $('#active-filters').addEventListener('click', event=>{
    const button=event.target.closest('[data-remove-filter]'); if(!button)return;
    $('#filters').elements.namedItem(button.dataset.removeFilter).value='';
    syncModels(); clearPreset(); page=1; loadList();
  });
  document.querySelectorAll('[data-preset]').forEach(button=>button.addEventListener('click',()=>{
    $('#filters').reset(); syncModels(); clearPreset(); button.setAttribute('aria-pressed','true');
    const fields=$('#filters').elements;
    if(button.dataset.preset==='deals'){fields.discount_min.value='10';fields.profit_min.value='0.01';fields.risk_max.value='40';$('#sort').value='profit';}
    if(button.dataset.preset==='low-risk')fields.risk_max.value='25';
    if(button.dataset.preset==='budget')fields.price_to.value='12000';
    page=1;loadList();
  }));
  $('#filters').addEventListener('submit', event => { event.preventDefault(); page=1; loadList(); });
  $('#sort').addEventListener('change', () => { page=1; loadList(); });
  $('#reset-filters').addEventListener('click', () => { $('#filters').reset(); syncModels(); clearPreset(); page=1; loadList(); });
  $('#prev-page').addEventListener('click', () => { if(page>1) {page--; loadList();} });
  $('#next-page').addEventListener('click', () => {page++; loadList();});
  $('#import-button').addEventListener('click', async () => {
    importing = true; $('#import-button').disabled = true; $('#import-button').textContent = 'Обновляем объявления…';
    try { const result = await api('/api/import', {method:'POST'}); notify(`Обновление завершено: новых ${result.created}, обновлено ${result.updated}, изменений цены ${result.price_changes}.`); }
    catch(error) { notify(error.message); }
    finally { importing=false; $('#import-button').textContent='↻  Обновить объявления'; $('#import-button').disabled=false; try {await loadStats(); await loadList();} catch(error) {notify(error.message);} }
  });
  try { let stats = await loadStats(); await loadList();
    // Подхватываем завершение первоначального импорта без перезагрузки страницы.
    const timer = setInterval(async () => { try { const fresh=await loadStats(); if (fresh.last_updated !== stats.last_updated) await loadList(); stats=fresh; } catch(error) { $('#stat-interval').textContent='Нет связи с сервером'; } }, 10000);
    window.addEventListener('pagehide', () => clearInterval(timer), {once:true});
  } catch(error) { notify(error.message); await loadList(); }
}
function renderDetail(item) {
  const s=item.score, exp=s?.explanation, r=risk(s?.risk_score);
  const specs=[['Год выпуска',item.year],['Пробег',item.mileage_km==null?null:number(item.mileage_km)+' км'],['Топливо',item.fuel_type],['Двигатель',item.engine_volume == null?null:item.engine_volume+' л'],['Коробка',item.transmission],['Привод',item.drive_type],['Город',item.city],['Область',item.region],['Поколение',item.generation],['Продавец',item.seller_type],['VIN',item.vin],['Первое наблюдение',date(item.first_seen_at)],['Последнее наблюдение',date(item.last_seen_at)],['Статус',item.is_active?'Активно':'Неактивно']];
  document.title=`${item.title} — ПЕРЕКУП`;
  $('#detail-content').innerHTML=`<div class="detail-heading"><div><p class="eyebrow">${item.source==='mock'?'ТЕСТОВОЕ ОБЪЯВЛЕНИЕ':'AUTO.RIA'} / ${esc(item.city||'УКРАИНА')}</p><h1>${esc(item.title)}</h1><span class="muted">${item.year} · ${item.mileage_km==null?'Пробег не указан':number(item.mileage_km)+' км'} · ${esc(item.transmission||'Коробка не указана')}</span></div>${item.url?`<a class="button primary" target="_blank" rel="noopener noreferrer" href="${esc(item.url)}">Открыть оригинал ↗</a>`:'<span class="tag">ДЕМО · НЕ ПРОДАЁТСЯ</span>'}</div>
  <div class="detail-grid"><div><section class="panel">${item.photos.length?`<img id="gallery-main" class="gallery-main" src="${esc(item.photos[0])}" alt="${item.source==='mock'?'Иллюстративное фото':esc(item.title)}" referrerpolicy="no-referrer"><div class="gallery-thumbs">${item.photos.map((url,i)=>`<button data-photo="${i}" aria-label="Показать фото ${i+1}"><img src="${esc(url)}" alt="Фото ${i+1}" referrerpolicy="no-referrer"></button>`).join('')}</div>`:'<div class="photo-empty">Фотографии не предоставлены</div>'}
  ${item.source==='mock'?'<p class="photo-note">Учебное объявление с вымышленной ценой. Фотографии показывают пример этой модели, а не конкретную машину продавца. В демо они могут повторяться внутри одной модели. <a href="/guide#photos">Авторы и лицензии ↗</a></p>':''}
  <dl class="specs">${specs.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v??'Не указано')}</dd></div>`).join('')}</dl></section>
  <section class="panel"><h2>Описание продавца</h2><p class="description">${esc(item.description||'Описание отсутствует')}</p></section>
  <section class="panel"><h2>История цены</h2><div id="price-chart" class="price-chart"></div><p class="muted">С момента первого наблюдения приложением.</p><table class="history"><thead><tr><th>Дата и время</th><th>Изменение</th><th>Цена</th></tr></thead><tbody>${item.price_history.map((p,i)=>`<tr><td>${date(p.recorded_at)}</td><td>${i?money(p.price_usd-item.price_history[i-1].price_usd):'Первая цена'}</td><td>${money(p.price_usd)}</td></tr>`).join('')}</tbody></table></section>
  <section class="panel"><h2>Аналоги для оценки · ${item.comparables.length}</h2><p class="muted">${exp?.region_preferred?'Подборка по тому же региону.':'Подборка по всем регионам.'} Явные выбросы исключены.</p>${item.comparables.length?item.comparables.map(x=>`<a class="comparable-row" href="/listings/${x.id}"><span>${esc(x.title)}<small>${x.year} · ${number(x.mileage_km)} км · ${esc(x.city)}</small></span><strong>${money(x.price_usd)} ↗</strong></a>`).join(''):'<p class="muted">Подходящих аналогов пока нет.</p>'}</section></div>
  <aside><section class="panel calculator"><h2>Экономика покупки</h2><div class="price-row"><strong>${money(item.price_usd)}</strong><span class="muted">Цена продавца</span></div>
  <div class="calc-row"><span>Оценка рынка</span><strong>${money(s?.estimated_market_price)}</strong></div><div class="calc-row"><span>Ниже рынка</span><strong>${s?.discount_percent==null?'—':number(s.discount_percent)+'%'}</strong></div>
  <form id="calculator"><label>Предполагаемый ремонт, $<input name="repair_cost" type="number" min="0" max="9999999999.99" step="0.01" required value="${s?.estimated_repair_cost??500}"></label><label>Дополнительные расходы, $<input name="additional_expenses" type="number" min="0" max="9999999999.99" step="0.01" required value="${s?.estimated_expenses??350}"></label>
  <div class="calc-profit"><span>Потенциальная прибыль</span><div><strong id="profit-preview">${money(s?.potential_profit)}</strong></div><small id="calc-note">${s?.estimated_market_price==null?'Недостаточно данных для расчёта':'Сохранённый расчёт с учётом расходов'}</small></div><button class="button primary full" type="submit">Пересчитать и сохранить</button></form>
  <p class="sidebar-help">Рынок − цена − ремонт − расходы. Суммы расходов сохраняются для этого автомобиля.</p></section>
  <section class="panel explanation"><h2>Почему такой балл</h2><div class="score-total"><span>${esc(exp?.status||'Не рассчитано')}</span><strong>${s?.total_score==null?'—':number(s.total_score)} <small>/ 100</small></strong></div><div class="score-track"><div id="score-fill" class="score-fill"></div></div>
  <p class="sidebar-help">Аналогов: ${exp?.comparable_count??0}; минимум: ${exp?.required_count??'—'}. Удалено выбросов: ${exp?.outliers_removed??0}.</p>${Object.entries(exp?.components||{}).map(([key,value])=>`<div class="calc-row"><span>${esc(key)}</span><strong>${value>0?'+':''}${number(value)}</strong></div>`).join('')}
  <p class="sidebar-help">${esc(exp?.liquidity_note||'')} Возраст объявления считается с первого наблюдения приложением.</p></section>
  <section class="panel"><h2>Риски и что проверить</h2><span class="risk ${r.className}">● ${r.label} риск · ${s?.risk_score??'—'} / 100</span><ul class="risk-list">${(exp?.risks||[]).map(x=>`<li><strong>${esc(x.phrase)}</strong> <span class="risk ${x.severity==='high'?'high':x.severity==='medium'?'medium':''}">+${x.points}</span><small>${esc(x.note)}</small></li>`).join('')||'<li>Стоп-фразы не найдены.<small>Это не подтверждает отсутствие проблем.</small></li>'}</ul>
  <p class="sidebar-help">Не указано: ${esc(exp?.missing_fields.join(', ')||'основные поля заполнены')}. Фотографий в базе: ${item.photos.length}.</p>
  ${Object.entries(exp?.risk_components||{}).map(([key,value])=>`<div class="calc-row"><span>${esc(key)}</span><strong>+${number(value)}</strong></div>`).join('')}</section></aside></div>`;
  drawPriceChart(item.price_history);
  $('#score-fill').style.width=`${s?.total_score||0}%`;
  document.querySelectorAll('[data-photo]').forEach(button=>button.addEventListener('click',()=>$('#gallery-main').src=item.photos[Number(button.dataset.photo)]));
  $('#calculator').addEventListener('input',()=>{const repair=Number($('#calculator').elements.repair_cost.value),expenses=Number($('#calculator').elements.additional_expenses.value); if(s?.estimated_market_price!=null && repair>=0 && expenses>=0) {$('#profit-preview').textContent=money(s.estimated_market_price-item.price_usd-repair-expenses);$('#calc-note').textContent='Предпросмотр · сохраните для пересчёта балла';}});
  $('#calculator').addEventListener('submit',async event=>{
    event.preventDefault(); const button=$('#calculator button');button.disabled=true;
    const payload=Object.fromEntries(new FormData($('#calculator')));
    try {await api(`/api/listings/${item.id}/calculate`,{method:'POST',body:JSON.stringify(payload)}); await loadDetail(item.id);notify('Расходы сохранены. Оценка пересчитана.');} catch(error){notify(error.message);button.disabled=false;}
  });
}
function drawPriceChart(history) {
  const host=$('#price-chart');
  if(!history.length)return;
  if(history.length<2){host.innerHTML='<p class="chart-note">График появится после первого изменения цены.</p>';return;}
  const recent=history.slice(-12), prices=recent.map(p=>p.price_usd);
  const low=Math.min(...prices), high=Math.max(...prices), span=Math.max(high-low,1);
  host.innerHTML='<div class="chart-bars" role="img" aria-label="История цены; точные значения в таблице ниже">'+recent.map(p=>`<div class="chart-column"><strong>${money(p.price_usd)}</strong><div class="chart-bar" style="height:${30+70*(p.price_usd-low)/span}px"></div><small>${date(p.recorded_at)}</small></div>`).join('')+'</div><p class="chart-note">Последние '+recent.length+' наблюдений · шкала сокращена, цены подписаны.</p>';
}
async function loadDetail(id){try{renderDetail(await api(`/api/listings/${id}`));}catch(error){$('#detail-content').innerHTML=`<div class="empty error">${esc(error.message)}</div>`;}}
if ($('#filters')) initCatalog();
if ($('#detail')) loadDetail($('#detail').dataset.id);
document.addEventListener('error', event=>{if(event.target instanceof HTMLImageElement){event.target.alt='Фото недоступно';event.target.style.objectFit='contain';}},true);
