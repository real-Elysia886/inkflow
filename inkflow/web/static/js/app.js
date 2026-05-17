/**
 * inkflow Web UI - Full Featured Application
 */
const API = '/api';
let currentProject = 'default';
let activeSocket = null; // Track active WebSocket for cleanup
let pollTimer = null; // Track distill polling timer
let cachedWorldState = null; // Cache world state to avoid duplicate requests
let cachedSkillMap = null; // Cache skill map for current project
let currentOperation = null; // Track current operation: { type, startTime, description }
let currentJobId = null; // Track current pipeline job ID for confirm

window.addEventListener('beforeunload', (e) => {
  if (currentOperation) {
    e.preventDefault();
    e.returnValue = '';
  }
});

// ── Utilities ──
async function api(path, opts = {}) {
  const headers = { ...opts.headers };
  if (opts.body && typeof opts.body === 'string' && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  const resp = await fetch(API + path, { headers, ...opts });
  if (!resp.ok) { const t = await resp.text(); let m; try { m = JSON.parse(t).detail || t; } catch { m = t; } throw new Error(m); }
  return resp.json();
}
function $(s, c = document) { return c.querySelector(s); }
function $$(s, c = document) { return [...c.querySelectorAll(s)]; }
function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
function setEl(sel, val) { const el = $(sel); if (el) el.textContent = val; }
function toast(msg, ok = true) { const e = document.createElement('div'); e.className = `toast ${ok ? 'toast-ok' : 'toast-err'}`; e.textContent = msg; document.body.appendChild(e); setTimeout(() => e.remove(), 3500); }
function showModal(title, body, onSave) {
  document.querySelectorAll('.modal-overlay').forEach(el => el.remove());
  const o = document.createElement('div'); o.className = 'modal-overlay';
  o.innerHTML = `<div class="modal"><h3></h3><div class="modal-body">${body}</div><div class="modal-actions"><button class="btn btn-outline cancel-btn">取消</button><button class="btn btn-primary save-btn">保存</button></div></div>`;
  o.querySelector('h3').textContent = title; // XSS-safe: use textContent for user-supplied title
  document.body.appendChild(o);
  o.querySelector('.cancel-btn').onclick = () => o.remove();
  o.querySelector('.save-btn').onclick = async () => { try { await onSave(o.querySelector('.modal-body')); o.remove(); } catch(e) { toast(e.message, false); } };
  o.onclick = e => { if (e.target === o) o.remove(); };
}

// ── Operation State Management ──
function setCurrentOperation(type, description) {
  currentOperation = { type, startTime: Date.now(), description };
  updateGenerateButtonState();
}
function clearCurrentOperation() {
  currentOperation = null;
  updateGenerateButtonState();
}
function updateGenerateButtonState() {
  const btn = $('#gen-btn');
  const cancelBtn = $('#cancel-btn');
  if (!btn) return;
  if (currentOperation) {
    btn.disabled = true;
    btn.dataset.originalText = btn.innerHTML;
    btn.innerHTML = `<span class="spinner"></span> ${currentOperation.description}进行中...`;
    if (cancelBtn) cancelBtn.style.display = 'inline-flex';
  } else {
    btn.disabled = false;
    if (btn.dataset.originalText) {
      btn.innerHTML = btn.dataset.originalText;
      delete btn.dataset.originalText;
    }
    if (cancelBtn) cancelBtn.style.display = 'none';
  }
}
function cancelCurrentOperation() {
  if (!currentOperation) return;
  const elapsed = Math.floor((Date.now() - currentOperation.startTime) / 1000);
  if (confirm(`当前操作：${currentOperation.description}\n已运行：${elapsed}秒\n\n确认终止？`)) {
    // Notify backend to cancel the pipeline
    if (currentJobId) {
      api(`/pipeline/cancel/${currentJobId}`, { method: 'POST' }).catch(() => {});
    }
    if (activeSocket) { try { activeSocket.close(); } catch(_) {} activeSocket = null; }
    clearCurrentOperation();
    toast('操作已终止');
  }
}

// ── Navigation ──
function initNav() {
  $$('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
      $$('.nav-item').forEach(n => n.classList.remove('active'));
      $$('.page').forEach(p => p.classList.remove('active'));
      item.classList.add('active');
      $(`#${item.dataset.page}`).classList.add('active');
      const p = item.dataset.page;
      
      // Close WebSocket on page navigation
      if (activeSocket) { try { activeSocket.close(); } catch(_) {} activeSocket = null; }
      // Stop distill polling on page navigation
      if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }

      // Update sidebar indicator
      if($('#current-project-sidebar')) $('#current-project-sidebar').textContent = currentProject;

      const pageLoaders = {
        'page-generate': loadGeneratePage,
        'page-chapters': loadChaptersPage,
        'page-skills': loadSkills,
        'page-world': loadWorldState,
        'page-projects': loadProjectsPage,
        'page-llm': loadLLMSettings,
        'page-workbench': loadWorkbench,
        'page-tokens': loadTokenStats,
      };
      pageLoaders[p]?.();
    });
  });
}

// ══════════════════════════════════════════
//  PROJECTS
// ══════════════════════════════════════════
let projects = [];

async function loadProjects() {
  try { projects = await api('/projects'); } catch (_) { projects = []; }
}

async function switchProject(pid) {
  currentProject = pid;
  localStorage.setItem('inkflow_project', pid);
  await loadGeneratePage();
  toast(`已切换到项目: ${pid}`);
}

async function loadProjectsPage() {
  try { await loadProjects(); } catch (_) {}
  const c = $('#projects-list');
  if (projects.length === 0) { c.innerHTML = '<p style="color:var(--text-muted)">暂无项目</p>'; return; }
  c.innerHTML = projects.map(p => `
    <div style="padding:12px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:8px;display:flex;justify-content:space-between;align-items:center">
      <div>
        <strong>${esc(p.name || p.project_id)}</strong>
        ${p.project_id === currentProject ? '<span class="badge badge-ok" style="margin-left:8px">当前</span>' : ''}
        <br><small style="color:var(--text2)">${esc(p.description || '')} · ${p.chapter_count || 0} 章</small>
      </div>
      <div style="display:flex;gap:6px">
        <button class="btn btn-sm btn-outline" onclick="switchProject('${esc(p.project_id)}')">切换</button>
        <button class="btn btn-sm btn-danger" onclick="deleteProject('${esc(p.project_id)}')">删除</button>
      </div>
    </div>
  `).join('');
}

function showCreateProjectModal() {
  showModal('新建项目', `
    <div class="form-group"><label>项目 ID</label><input id="m-id" placeholder="my-novel"></div>
    <div class="form-group"><label>名称</label><input id="m-name" placeholder="我的小说"></div>
    <div class="form-group"><label>描述</label><textarea id="m-desc" placeholder="一个关于..."></textarea></div>
  `, async (body) => {
    await api('/projects', { method: 'POST', body: JSON.stringify({
      project_id: body.querySelector('#m-id').value,
      name: body.querySelector('#m-name').value,
      description: body.querySelector('#m-desc').value,
    })});
    toast('项目已创建'); loadProjectsPage();
  });
}

async function deleteProject(pid) {
  if (!confirm(`删除项目 "${pid}"？所有章节和数据将丢失！`)) return;
  try {
    await api(`/projects/${pid}`, { method: 'DELETE' });
    if (currentProject === pid) { currentProject = 'default'; localStorage.setItem('inkflow_project', 'default'); }
    toast('已删除'); loadProjectsPage();
  } catch (e) { toast('删除失败: ' + e.message, false); }
}

// ══════════════════════════════════════════
//  ONE-CLICK GENERATE
// ══════════════════════════════════════════
async function loadGeneratePage() {
  try {
    // 每次都重新获取数据以确保最新
    const ws = await api(`/world?project_id=${currentProject}`);
    cachedWorldState = ws;
    const chNum = ws.current_chapter || 0;
    setEl('#stat-chapter', chNum);
    setEl('#stat-chapter-top', chNum);
    setEl('#next-chapter', chNum + 1);
    setEl('#stat-chars', Object.keys(ws.characters || {}).length);
    setEl('#stat-foreshadow', (ws.foreshadowing_pool || []).filter(f => f.status === 'pending').length);
    setEl('#stat-threads', (ws.plot_threads || []).filter(t => t.status === 'active').length);
    // Load feedback for avg rating
    try {
      const fb = await api(`/projects/${currentProject}/feedback`);
      setEl('#stat-avg-rating', fb.length > 0 ? (fb.reduce((s, f) => s + f.rating, 0) / fb.length).toFixed(1) + '★' : '-');
    } catch (_) { setEl('#stat-avg-rating', '-'); }
    // Load project name
    try {
      const p = await api(`/projects/${currentProject}`);
      setEl('#current-project-name', p.name || currentProject);
    } catch (_) {}
    // Load skill map
    try {
      const smRes = await api(`/projects/${currentProject}/skill-map`);
      cachedSkillMap = (smRes && smRes.skill_map) || null;
    } catch (_) { cachedSkillMap = null; }
    loadOutlines();
    // Check for active jobs and reconnect
    try {
      const activeJobs = await api(`/pipeline/active-jobs/${currentProject}`);
      if (activeJobs && activeJobs.length > 0 && !currentOperation) {
        reconnectToJob(activeJobs[0]);
      } else {
        const progCard = $('#gen-progress');
        if (progCard && !currentOperation) progCard.style.display = 'none';
      }
    } catch (_) {
      const progCard = $('#gen-progress');
      if (progCard && !currentOperation) progCard.style.display = 'none';
    }
  } catch (err) {
    console.error('Failed to load generate page:', err);
    toast('加载项目数据失败: ' + err.message, false);
  }
}

// ══════════════════════════════════════════
//  SKILL CONFIG MODAL
// ══════════════════════════════════════════
async function showSkillConfigModal() {
  const roles = ['editor', 'writer', 'librarian', 'strategist', 'prophet'];
  const roleLabels = { editor: '编辑', writer: '写手', librarian: '图书管理员', strategist: '策略师', prophet: '大纲师' };

  let allSkills = [];
  let currentMap = {};
  try {
    const [skillsRes, mapRes] = await Promise.all([
      api('/skills'),
      api(`/projects/${currentProject}/skill-map`)
    ]);
    allSkills = skillsRes || [];
    currentMap = (mapRes && mapRes.skill_map) || {};
  } catch (_) {}

  let html = '<p style="color:var(--text-dim);margin-bottom:16px">为每个角色类型选择要使用的技能。不选择则自动使用蒸馏版本（如有）。</p>';
  for (const role of roles) {
    const skills = allSkills.filter(s => s.skill_type === role);
    const current = currentMap[role] || '';
    html += `<div class="form-group"><label>${roleLabels[role] || role}</label><select id="m-skill-${role}" class="select-styled" style="width:100%">
      <option value="">自动（优先蒸馏）</option>`;
    for (const s of skills) {
      const selected = s.slug === current ? 'selected' : '';
      const tag = s.version === 'base' ? ' [基础]' : ' [蒸馏]';
      html += `<option value="${esc(s.slug)}" ${selected}>${esc(s.display_name || s.slug)}${tag}</option>`;
    }
    html += '</select></div>';
  }

  showModal('🎯 技能配置', html, async () => {
    const skillMap = {};
    for (const role of roles) {
      const val = $(`#m-skill-${role}`).value;
      if (val) skillMap[role] = val;
    }
    await api(`/projects/${currentProject}/skill-map`, { method: 'PUT', body: JSON.stringify(skillMap) });
    cachedSkillMap = Object.keys(skillMap).length > 0 ? skillMap : null;
    toast('技能配置已保存');
  });
}

// ══════════════════════════════════════════
//  QUICK START WIZARD
// ══════════════════════════════════════════
function showQuickStartWizard() {
  showModal('快速入门向导', `
    <p style="color:var(--text-dim);margin-bottom:16px">输入几个关键词，AI 将自动生成世界观、角色和大纲，帮你快速开书。</p>
    <div class="form-group"><label>小说类型</label><select id="m-genre" onchange="document.getElementById('m-genre-custom-wrap').style.display=this.value==='其他'?'block':'none'">
      <option value="">选择类型...</option>
      <option value="玄幻修仙">玄幻修仙</option>
      <option value="都市异能">都市异能</option>
      <option value="科幻未来">科幻未来</option>
      <option value="历史架空">历史架空</option>
      <option value="悬疑推理">悬疑推理</option>
      <option value="末日废土">末日废土</option>
      <option value="游戏竞技">游戏竞技</option>
      <option value="奇幻冒险">奇幻冒险</option>
      <option value="其他">其他</option>
    </select><div id="m-genre-custom-wrap" style="display:none;margin-top:8px"><input id="m-genre-custom" placeholder="请输入自定义类型"></div></div>
    <div class="form-group"><label>核心关键词（用逗号分隔）</label><input id="m-keywords" placeholder="例：重生、系统流、逆袭"></div>
    <div class="form-group"><label>主角描述</label><textarea id="m-protagonist" rows="2" placeholder="例：一个被陷害的天才少年，性格坚韧"></textarea></div>
    <div class="form-group"><label>整体基调</label><select id="m-tone" onchange="document.getElementById('m-tone-custom-wrap').style.display=this.value==='其他'?'block':'none'">
      <option value="">选择基调...</option>
      <option value="热血爽文">热血爽文</option>
      <option value="轻松幽默">轻松幽默</option>
      <option value="暗黑严肃">暗黑严肃</option>
      <option value="温馨治愈">温馨治愈</option>
      <option value="紧张悬疑">紧张悬疑</option>
      <option value="其他">其他</option>
    </select><div id="m-tone-custom-wrap" style="display:none;margin-top:8px"><input id="m-tone-custom" placeholder="请输入自定义基调"></div></div>
  `, async b => {
    let genre = b.querySelector('#m-genre').value;
    if (genre === '其他') genre = b.querySelector('#m-genre-custom').value.trim();
    const keywords = b.querySelector('#m-keywords').value;
    const protagonist = b.querySelector('#m-protagonist').value;
    let tone = b.querySelector('#m-tone').value;
    if (tone === '其他') tone = b.querySelector('#m-tone-custom').value.trim();
    if (!keywords && !protagonist) throw new Error('请至少填写关键词或主角描述');

    setCurrentOperation('quick-start', '快速入门设定生成');
    try {
      const result = await api('/pipeline/quick-start', {
        method: 'POST',
        body: JSON.stringify({ project_id: currentProject, genre, keywords, protagonist, tone })
      });
      cachedWorldState = null;
      toast('设定生成完成！');
      loadGeneratePage();
      loadWorldState();
    } finally {
      clearCurrentOperation();
    }
  });
}

// ── Result Modal ──
let lastGenerationResult = null;
let lastGenerationChapter = 0;
let currentResultOverlay = null;

function showLastResultModal() {
  // 如果已有隐藏的弹窗，直接显示
  if (currentResultOverlay) {
    currentResultOverlay.style.display = 'flex';
    return;
  }
  if (!lastGenerationResult) {
    toast('暂无生成结果', false);
    return;
  }
  currentResultOverlay = showResultModal(lastGenerationChapter);
  displayResultInModal(currentResultOverlay, lastGenerationResult);
}

function hideResultModal() {
  if (currentResultOverlay) {
    currentResultOverlay.style.display = 'none';
  }
}

function showResultModal(chapterNumber) {
  // 移除之前可能存在的弹窗
  document.querySelectorAll('.result-modal-overlay').forEach(el => el.remove());

  const overlay = document.createElement('div');
  overlay.className = 'result-modal-overlay';
  overlay.innerHTML = `
    <div class="result-modal">
      <div class="result-modal-header">
        <h3>第 ${chapterNumber} 章 - 生成结果</h3>
        <div style="display:flex;align-items:center;gap:12px">
          <div id="result-score-badge"></div>
          <button class="btn btn-outline" onclick="hideResultModal()">关闭</button>
        </div>
      </div>
      <div class="result-modal-body">
        <div class="result-modal-tabs">
          <button class="tab-btn active" data-tab="result-tab-text">章节正文</button>
          <button class="tab-btn" data-tab="result-tab-eval">审校分析报告</button>
        </div>
        <div class="result-modal-content">
          <div id="result-tab-text" class="tab-panel active">
            <textarea class="stream-textarea" id="result-text" placeholder="章节正文将在此显示，审阅后可编辑..."></textarea>
          </div>
          <div id="result-tab-eval" class="tab-panel">
            <div id="result-eval-detail"></div>
          </div>
        </div>
      </div>
      <div class="feedback-bar">
        <div id="result-feedback-stars" class="stars-rating">
          <span data-star="1" onclick="setRating(1)">☆</span>
          <span data-star="2" onclick="setRating(2)">☆</span>
          <span data-star="3" onclick="setRating(3)">☆</span>
          <span data-star="4" onclick="setRating(4)">☆</span>
          <span data-star="5" onclick="setRating(5)">☆</span>
        </div>
        <input id="result-feedback-comment" style="flex:1" placeholder="对此章节的改进建议（如：节奏太快、角色崩坏）...">
        <button class="btn btn-outline" onclick="rejectChapter(${chapterNumber})" style="border-color:var(--danger);color:var(--danger)">打回重写</button>
        <button class="btn btn-primary" onclick="confirmChapter(${chapterNumber})">保存并提交</button>
      </div>
    </div>
  `;

  document.body.appendChild(overlay);

  // 绑定标签切换
  overlay.querySelectorAll('.result-modal-tabs .tab-btn').forEach(btn => {
    btn.onclick = () => {
      overlay.querySelectorAll('.result-modal-tabs .tab-btn').forEach(b => b.classList.remove('active'));
      overlay.querySelectorAll('.result-modal-content .tab-panel').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      overlay.querySelector(`#${btn.dataset.tab}`).classList.add('active');
    };
  });

  // 点击遮罩隐藏（而不是删除）
  overlay.onclick = e => { if (e.target === overlay) hideResultModal(); };

  currentResultOverlay = overlay;
  return overlay;
}

function displayResultInModal(overlay, result) {
  const ev = result.evaluation || {};
  const score = ev.total_score || 0;
  const antiAiScore = ev.anti_ai_score;

  // 更新分数徽章
  const badgeEl = overlay.querySelector('#result-score-badge');
  if (badgeEl) {
    const antiAiBadge = antiAiScore != null
      ? ` <span class="score-badge ${antiAiScore >= 60 ? 'pass' : 'fail'}" style="font-size:0.78rem;margin-left:6px">AI味 ${antiAiScore}/100</span>`
      : '';
    badgeEl.innerHTML = `<span class="score-badge ${result.passed ? 'pass' : 'fail'}">${score}/70 ${result.passed ? '通过' : '需修改'}</span>${antiAiBadge}`;
  }

  // 更新文本
  const textEl = overlay.querySelector('#result-text');
  if (textEl) {
    textEl.value = result.final_text || '';
  }

  // 渲染审校报告
  const evalEl = overlay.querySelector('#result-eval-detail');
  if (evalEl) {
    evalEl.innerHTML = renderEvaluationReport(ev);
  }
}

function renderEvaluationReport(ev) {
  let html = '';

  if (ev.issues && ev.issues.length) {
    html += `<div style="margin:12px 0"><strong>问题</strong>`;
    html += ev.issues.map(i => `
      <div class="issue-item ${i.severity||'medium'}">
        [${esc(i.severity||'')}] ${esc(i.category||'')}: ${esc(i.description||'')}
        <br><small style="color:var(--text2)">建议: ${esc(i.suggestion||'')}</small>
      </div>
    `).join('');
    html += '</div>';
  }

  if (ev.highlights && ev.highlights.length) {
    html += `<div style="margin:12px 0"><strong>亮点</strong><ul style="margin:4px 0;padding-left:20px">`;
    html += ev.highlights.map(h => `<li>${esc(h)}</li>`).join('');
    html += '</ul></div>';
  }

  if (ev.anti_ai_learning && ev.anti_ai_learning.length) {
    html += `<div style="margin:12px 0"><details>
      <summary style="cursor:pointer;color:var(--primary);font-weight:600">📖 去 AI 味学习 (${ev.anti_ai_learning.length} 条)</summary>
      <div style="margin-top:8px">`;
    html += ev.anti_ai_learning.map(ex => {
      const ctxHtml = (ex.contexts||[]).map(c =>
        `<code style="background:var(--surface3);padding:2px 6px;border-radius:3px;font-size:0.8rem;display:inline-block;margin:2px 0">${esc(c)}</code>`
      ).join('<br>');
      return `
        <div class="card" style="margin:8px 0;background:var(--surface2);border-left:3px solid var(--warning)">
          <div style="font-weight:600;margin-bottom:6px">
            ${esc(ex.type==='fatigue_word' ? '🔤 '+ex.keyword : '📐 句式问题')}
            <span class="badge badge-warn" style="margin-left:6px">${ex.count}次</span>
          </div>
          <div style="font-size:0.85rem;color:var(--text2);margin-bottom:8px">${esc(ex.diagnosis)}</div>
          <div style="font-size:0.8rem;line-height:1.4"><strong>上下文:</strong><br>${ctxHtml}</div>
          <div style="margin-top:8px;font-size:0.85rem;padding:8px;background:var(--surface3);border-radius:4px;border:1px dashed var(--border)">
            <strong>建议改法:</strong><br>${esc(ex.improved || ex.fix_suggestion || '')}
          </div>
        </div>`;
    }).join('');
    html += '</div></details></div>';
  }

  return html || '<p style="color:var(--text2)">暂无审校报告</p>';
}

async function generateAuto() {
  const count = parseInt($('#auto-chapter-count').value) || 1;
  if (count < 1 || count > 50) return toast('章节数需在 1-50 之间', false);
  if (currentOperation) {
    toast(`${currentOperation.description}正在进行，请等待完成或终止`, false);
    return;
  }

  const btn = $('#auto-gen-btn');
  btn.disabled = true;
  setCurrentOperation('auto_generate', `全自动生成 ${count} 章`);

  const log = $('#gen-log');
  const progCard = $('#gen-progress');
  progCard.style.display = 'block';
  log.innerHTML = '';

  for (let i = 0; i < count; i++) {
    const chapterNum = (cachedWorldState?.current_chapter || 0) + i + 1;
    log.insertAdjacentHTML('beforeend', `<div class="log-entry" style="color:var(--primary)">[全自动] 开始生成第 ${chapterNum} 章 (${i+1}/${count})</div>`);
    log.scrollTop = log.scrollHeight;
    btn.textContent = `🤖 生成中 ${i+1}/${count}`;

    try {
      const res = await api('/pipeline/generate', {
        method: 'POST',
        body: JSON.stringify({ project_id: currentProject, speed_mode: 'full_auto' }),
      });

      // Wait for completion via polling
      await new Promise((resolve, reject) => {
        const pollInterval = setInterval(async () => {
          try {
            const status = await api(`/pipeline/status/${res.job_id}`);
            if (status.status === 'completed') {
              clearInterval(pollInterval);
              log.insertAdjacentHTML('beforeend', `<div class="log-entry" style="color:var(--success)">[全自动] 第 ${chapterNum} 章完成</div>`);
              log.scrollTop = log.scrollHeight;
              resolve();
            } else if (status.status === 'failed') {
              clearInterval(pollInterval);
              log.insertAdjacentHTML('beforeend', `<div class="log-entry" style="color:var(--danger)">[全自动] 第 ${chapterNum} 章失败: ${status.error || '未知错误'}</div>`);
              log.scrollTop = log.scrollHeight;
              reject(new Error(status.error));
            }
          } catch (e) {
            // Ignore polling errors, keep trying
          }
        }, 2000);
      });

      // Refresh world state cache after each chapter
      cachedWorldState = null;

    } catch (e) {
      log.insertAdjacentHTML('beforeend', `<div class="log-entry" style="color:var(--danger)">[全自动] 中止: ${e.message}</div>`);
      break;
    }
  }

  log.insertAdjacentHTML('beforeend', `<div class="log-entry" style="color:var(--primary)">[全自动] 全部完成</div>`);
  log.scrollTop = log.scrollHeight;
  btn.disabled = false;
  btn.textContent = '🤖 全自动生成';
  clearCurrentOperation();
  cachedWorldState = null;
  loadGeneratePage();
  toast(`全自动生成完成`);
}

function reconnectToJob(job) {
  // Restore UI state for an active job
  setCurrentOperation('generate', '章节生成（重连）');
  currentJobId = job.job_id;
  const btn = $('#gen-btn'); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> 生成中...';
  const progCard = $('#gen-progress');
  progCard.style.display = 'block';
  const bar = $('#gen-progress-bar');

  // Show preview button if already in preview_ready state
  if (job.status === 'preview_ready') {
    const previewBtn = $('#preview-review-btn');
    if (previewBtn) previewBtn.style.display = 'inline-flex';
    bar.style.width = '90%'; bar.textContent = '等待审阅';
  }

  // Close existing WebSocket
  if (activeSocket) { try { activeSocket.close(); } catch(_) {} activeSocket = null; }

  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${location.host}/api/pipeline/ws/${job.job_id}`;
  const socket = new WebSocket(wsUrl);
  activeSocket = socket;

  const stages = ['outline', 'plan', 'compose', 'writer', 'editor', 'human', 'observer', 'reflector', 'librarian'];
  let resultOverlay = null;
  const nextChapter = (cachedWorldState?.current_chapter || 0) + 1;
  const log = $('#gen-log');

  socket.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    console.log('Reconnect WS message:', msg.type, msg.data);

    if (msg.type === 'stream_chunk') {
      if (!resultOverlay) resultOverlay = showResultModal(nextChapter);
      const textEl = resultOverlay.querySelector('#result-text');
      if (textEl) { textEl.value += msg.data.chunk; textEl.scrollTop = textEl.scrollHeight; }
      const writerStep = $('#step-writer');
      if (writerStep) { writerStep.classList.add('active'); writerStep.classList.remove('done'); }
    } else if (msg.type === 'progress') {
      const p = msg.data;
      if (p.stage === 'writer_stream') return;
      const time = new Date().toLocaleTimeString();
      log.insertAdjacentHTML('beforeend', `<div class="log-entry"><span class="log-time">[${time}]</span> <span class="log-stage">${esc(p.stage)}</span>: ${esc(p.message)}</div>`);
      const currentIdx = stages.indexOf(p.stage);
      for (let i = 0; i < stages.length; i++) {
        const s = $(`#step-${stages[i]}`); const c = $(`#conn-${stages[i]}`);
        if (i < currentIdx) { if (s) { s.classList.add('done'); s.classList.remove('active'); } if (c) c.classList.add('done'); }
        else if (i === currentIdx) { if (s) { s.classList.add('active'); s.classList.remove('done'); } }
      }
      if (currentIdx !== -1) { const pct = Math.floor(((currentIdx + 1) / stages.length) * 100); bar.style.width = pct + '%'; bar.textContent = pct + '%'; }
      log.scrollTop = log.scrollHeight;
    } else if (msg.type === 'preview_ready') {
      const result = msg.data;
      bar.style.width = '90%'; bar.textContent = '等待审阅';
      $('#step-human').className = 'pipeline-step active';
      lastGenerationResult = result;
      lastGenerationChapter = result.chapter_number || (cachedWorldState?.current_chapter || 0) + 1;
      if (resultOverlay) { displayResultInModal(resultOverlay, result); currentResultOverlay = resultOverlay; }
      else { resultOverlay = showResultModal(lastGenerationChapter); displayResultInModal(resultOverlay, result); currentResultOverlay = resultOverlay; }
      btn.textContent = '等待审阅...';
      const previewBtn = $('#preview-review-btn');
      if (previewBtn) previewBtn.style.display = 'inline-flex';
    } else if (msg.type === 'completed') {
      const result = msg.data;
      bar.style.width = '100%'; bar.textContent = '完成';
      $('#step-human').className = 'pipeline-step done';
      lastGenerationResult = result; lastGenerationChapter = result.chapter_number || lastGenerationChapter;
      hideResultModal(); loadGeneratePage();
      socket.close(); btn.disabled = false; btn.textContent = '一键生成下一章';
      currentJobId = null; clearCurrentOperation(); toast('章节已保存');
    } else if (msg.type === 'failed') {
      btn.disabled = false; btn.textContent = '一键生成下一章';
      toast('生成失败', false); socket.close(); clearCurrentOperation();
      if (resultOverlay) hideResultModal();
    } else if (msg.type === 'cancelled') {
      btn.disabled = false; btn.textContent = '一键生成下一章';
      log.insertAdjacentHTML('beforeend', '<div class="log-entry" style="color:var(--warning)">[取消] 任务已被终止</div>');
      socket.close(); clearCurrentOperation();
      if (resultOverlay) hideResultModal();
    }
  };

  socket.onclose = () => { console.log('Reconnect WebSocket closed'); };
  toast('已重连到进行中的任务');
}

async function generateChapter() {
  if (currentOperation) {
    toast(`${currentOperation.description}正在进行，请等待完成或终止`, false);
    return;
  }
  // Check if world state is empty, suggest quick start
  const ws = cachedWorldState;
  if (ws && ws.current_chapter === 0 && Object.keys(ws.characters || {}).length === 0 && !ws.world_setting) {
    if (confirm('当前项目没有世界观和角色设定，是否先使用「快速入门向导」？\n\n点「确定」打开向导，点「取消」直接由 AI 自动创作。')) {
      showQuickStartWizard();
      return;
    }
  }

  setCurrentOperation('generate', '章节生成');
  const btn = $('#gen-btn'); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> 生成中...';
  const progCard = $('#gen-progress');
  progCard.style.display = 'block'; $('#gen-log').innerHTML = '';
  ['outline','plan','compose','writer','editor','observer','reflector','librarian'].forEach(s => {
    const el = $(`#step-${s}`); if(el) el.className = 'pipeline-step';
    const conn = $(`#conn-${s}`); if(conn) conn.className = 'pipeline-connector';
  });

  const bar = $('#gen-progress-bar');
  if (bar) { bar.style.width = '0%'; bar.textContent = ''; }

  try {
    const speedMode = $('#speed-mode').value;
    const startRes = await api('/pipeline/generate', { method: 'POST', body: JSON.stringify({ project_id: currentProject, speed_mode: speedMode, skill_map: cachedSkillMap || null }) });
    const jobId = startRes.job_id;
    currentJobId = jobId;

    // 结果弹窗（延迟创建，检测到流式输出时才显示）
    let resultOverlay = null;
    const nextChapter = (cachedWorldState?.current_chapter || 0) + 1;

    // Close any existing WebSocket before opening a new one
    if (activeSocket) { try { activeSocket.close(); } catch(_) {} activeSocket = null; }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/api/pipeline/ws/${jobId}`;
    const socket = new WebSocket(wsUrl);
    activeSocket = socket;

    const stages = ['outline', 'plan', 'compose', 'writer', 'editor', 'human', 'observer', 'reflector', 'librarian'];

    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      const log = $('#gen-log');
      console.log('WebSocket message:', msg.type, msg.data);

      if (msg.type === 'stream_chunk') {
        // 检测到流式输出时才创建弹窗
        if (!resultOverlay) {
          resultOverlay = showResultModal(nextChapter);
          // 显示预览校对按钮
          const previewBtn = $('#preview-review-btn');
          if (previewBtn) previewBtn.style.display = 'inline-flex';
        }
        // Streaming text chunk to result modal
        const textEl = resultOverlay.querySelector('#result-text');
        if (textEl) {
          textEl.value += msg.data.chunk;
          textEl.scrollTop = textEl.scrollHeight;
        }
        // Mark writer step as active when streaming starts
        const writerStep = $('#step-writer');
        if (writerStep) { writerStep.classList.add('active'); writerStep.classList.remove('done'); }
      } else if (msg.type === 'progress') {
        const p = msg.data;
        if (p.stage === 'writer_stream') return;
        const time = new Date().toLocaleTimeString();
        log.insertAdjacentHTML('beforeend', `<div class="log-entry"><span class="log-time">[${time}]</span> <span class="log-stage">${esc(p.stage)}</span>: ${esc(p.message)}</div>`);

        const currentIdx = stages.indexOf(p.stage);
        for (let i = 0; i < stages.length; i++) {
          const s = $(`#step-${stages[i]}`);
          const c = $(`#conn-${stages[i]}`);
          if (i < currentIdx) {
            if (s) { s.classList.add('done'); s.classList.remove('active'); }
            if (c) c.classList.add('done');
          } else if (i === currentIdx) {
            if (s) { s.classList.add('active'); s.classList.remove('done'); }
          }
        }

        if (currentIdx !== -1) {
          const pct = Math.floor(((currentIdx + 1) / stages.length) * 100);
          bar.style.width = pct + '%';
          bar.textContent = pct + '%';
        }
        log.scrollTop = log.scrollHeight;
      } else if (msg.type === 'preview_ready') {
        // Phase 1 complete: pipeline paused for human review
        const result = msg.data;
        bar.style.width = '90%'; bar.textContent = '等待审阅';
        $('#step-human').className = 'pipeline-step active';
        lastGenerationResult = result;
        lastGenerationChapter = result.chapter_number || (cachedWorldState?.current_chapter || 0) + 1;
        // Show result modal for review
        if (resultOverlay) {
          displayResultInModal(resultOverlay, result);
          currentResultOverlay = resultOverlay;
        } else {
          resultOverlay = showResultModal(lastGenerationChapter);
          displayResultInModal(resultOverlay, result);
          currentResultOverlay = resultOverlay;
        }
        // Keep button disabled, show waiting state
        btn.textContent = '等待审阅...';
        // Re-enable modal buttons (in case this is a rewrite)
        const modalBtns = document.querySelectorAll('.result-modal-overlay .btn');
        modalBtns.forEach(b => { b.disabled = false; });
        const rejectBtn = document.querySelector('.result-modal-overlay .btn-outline[onclick*="rejectChapter"]');
        if (rejectBtn) rejectBtn.textContent = '打回重写';
        log.insertAdjacentHTML('beforeend', '<div class="log-entry" style="color:var(--primary)">[审阅] 流水线已暂停，等待人工审阅后点击"保存并提交"</div>');
        log.scrollTop = log.scrollHeight;
        // Don't close socket - wait for confirm
      } else if (msg.type === 'completed') {
        // Phase 2 complete: human confirmed, post-review steps done
        const result = msg.data;
        bar.style.width = '100%'; bar.textContent = '完成';
        $('#step-human').className = 'pipeline-step done';
        lastGenerationResult = result;
        lastGenerationChapter = result.chapter_number || lastGenerationChapter;
        hideResultModal();
        loadGeneratePage();
        socket.close();
        btn.disabled = false; btn.textContent = '一键生成下一章';
        currentJobId = null;
        clearCurrentOperation();
        toast('章节已保存');
      } else if (msg.type === 'failed') {
        const error = msg.data.error;
        btn.disabled = false; btn.textContent = '一键生成下一章';
        toast('生成失败: ' + (error || '未知错误'), false);
        log.insertAdjacentHTML('beforeend', `<div class="log-entry" style="color:var(--danger)">[ERROR] ${esc(error)}</div>`);
        socket.close();
        clearCurrentOperation();
        // 隐藏弹窗（而不是删除）
        if (resultOverlay) hideResultModal();
      } else if (msg.type === 'cancelled') {
        btn.disabled = false; btn.textContent = '一键生成下一章';
        log.insertAdjacentHTML('beforeend', '<div class="log-entry" style="color:var(--warning)">[取消] 任务已被终止</div>');
        socket.close();
        clearCurrentOperation();
        if (resultOverlay) hideResultModal();
      }
    };

    socket.onerror = (error) => {
      console.error('WebSocket Error:', error);
      btn.disabled = false; btn.textContent = '一键生成下一章';
      toast('WebSocket 连接失败，请检查网络', false);
      clearCurrentOperation();
      if (resultOverlay) hideResultModal();
    };

    socket.onclose = () => {
      console.log('WebSocket connection closed');
    };

  } catch (e) {
    btn.disabled = false; btn.textContent = '一键生成下一章';
    toast(e.message, false);
    clearCurrentOperation();
  }
}

let currentRating = 0;
function setRating(n) {
  currentRating = n;
  // 同时更新主页面和弹窗中的星星
  $$('#feedback-stars span, #result-feedback-stars span').forEach(s => {
    const v = parseInt(s.dataset.star);
    s.textContent = v <= n ? '★' : '☆';
    s.style.color = v <= n ? 'var(--warning)' : 'var(--text2)';
  });
}

async function rejectChapter(chNum) {
  if (!currentJobId) {
    toast('无待确认的任务', false);
    return;
  }

  // Get rejection reason from the comment input
  const reason = document.querySelector('.result-modal-overlay #result-feedback-comment')?.value || '';
  if (!reason.trim()) {
    toast('请在输入框中说明打回原因', false);
    return;
  }

  const btn = document.querySelector('.result-modal-overlay .btn-outline[onclick*="rejectChapter"]');
  if (btn) { btn.disabled = true; btn.textContent = '重写中...'; }

  try {
    await api('/pipeline/rewrite', {
      method: 'POST',
      body: JSON.stringify({
        job_id: currentJobId,
        project_id: currentProject,
        reason: reason,
      }),
    });
    toast('已打回，正在重写...');
    // The WebSocket will receive new progress messages
  } catch (e) {
    toast('打回失败: ' + e.message, false);
    if (btn) { btn.disabled = false; btn.textContent = '打回重写'; }
  }
}

async function confirmChapter(chNum) {
  if (!currentJobId) {
    toast('无待确认的任务', false);
    return;
  }

  // Get edited text from the modal textarea
  const textEl = document.querySelector('.result-modal-overlay #result-text');
  const editedText = textEl ? textEl.value : '';

  // Get optional feedback
  const comment = document.querySelector('.result-modal-overlay #result-feedback-comment')?.value || '';

  const btn = document.querySelector('.result-modal-overlay .btn-primary');
  if (btn) { btn.disabled = true; btn.textContent = '提交中...'; }

  try {
    // Submit feedback if rating given
    if (currentRating > 0) {
      await api(`/projects/${currentProject}/feedback`, {
        method: 'POST',
        body: JSON.stringify({ chapter_number: chNum, rating: currentRating, comment }),
      });
    }

    // Confirm the chapter (triggers ObserveReflect + Librarian)
    await api('/pipeline/confirm', {
      method: 'POST',
      body: JSON.stringify({
        job_id: currentJobId,
        project_id: currentProject,
        edited_text: editedText,
      }),
    });

    // Success - the WebSocket will receive "completed" message
    currentRating = 0;

  } catch (e) {
    toast('提交失败: ' + e.message, false);
    if (btn) { btn.disabled = false; btn.textContent = '保存并提交'; }
  }
}

async function submitFeedback(chNum) {
  // 优先从弹窗获取评论，否则从主页面获取
  const comment = document.querySelector('.result-modal-overlay #result-feedback-comment')?.value
    || $('#feedback-comment')?.value
    || '';
  if (currentRating === 0) return toast('请先评分', false);
  try {
    await api(`/projects/${currentProject}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ chapter_number: chNum, rating: currentRating, comment }),
    });
    toast('反馈已提交，会影响后续生成');
    // 隐藏弹窗（而不是删除）
    hideResultModal();
    // 清空反馈表单
    currentRating = 0;
    const commentEl = $('#feedback-comment');
    if (commentEl) commentEl.value = '';
    $$('#feedback-stars span, #result-feedback-stars span').forEach(s => {
      s.textContent = '☆';
      s.style.color = 'var(--text2)';
    });
    // 清除结果引用（已提交完成）
    lastGenerationResult = null;
    currentResultOverlay = null;
    // 隐藏预览按钮
    const previewBtn = $('#preview-review-btn');
    if (previewBtn) previewBtn.style.display = 'none';
    // 刷新页面显示最新状态
    cachedWorldState = null;
    loadGeneratePage();
  } catch (e) { toast('提交失败: ' + e.message, false); }
}

// ══════════════════════════════════════════
//  CHAPTERS BROWSER + EDITOR
// ══════════════════════════════════════════
async function loadChaptersPage() {
  try {
    const chapters = await api(`/projects/${currentProject}/chapters`);
    const c = $('#chapters-list');
    if (!chapters.length) { c.innerHTML = '<p style="color:var(--text2);text-align:center;padding:40px">暂无章节，请先「一键生成」</p>'; return; }
    c.innerHTML = chapters.map(ch => `
      <div style="padding:12px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:8px;cursor:pointer" onclick="viewChapter(${ch.chapter_number})">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div>
            <strong style="color:var(--primary)">第${ch.chapter_number}章</strong> ${esc(ch.title || '')}
            ${ch.rating ? `<span style="color:var(--warning);margin-left:8px">${'★'.repeat(ch.rating)}${'☆'.repeat(5-ch.rating)}</span>` : ''}
            ${ch.edited_by_human ? '<span class="badge badge-info" style="margin-left:8px">已编辑</span>' : ''}
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:0.8rem;color:var(--text2)">${ch.word_count || 0} 字</span>
            <button class="btn btn-outline btn-sm" style="padding:2px 8px;font-size:0.75rem" onclick="event.stopPropagation(); rewriteChapter(${ch.chapter_number})" title="重写章节">重写</button>
            <button class="btn btn-outline btn-sm" style="color:var(--danger);border-color:var(--danger);padding:2px 8px;font-size:0.75rem" onclick="event.stopPropagation(); deleteChapter(${ch.chapter_number})" title="删除章节">×</button>
          </div>
        </div>
      </div>
    `).join('');
  } catch (e) { toast('加载失败: ' + e.message, false); }
}

// ── Import chapters ──
async function importSingleChapter() {
  const chNum = parseInt($('#import-start-ch').value) || 1;
  const text = prompt(`粘贴第 ${chNum} 章正文（至少 50 字）：`);
  if (!text || text.length < 50) return toast('正文太短', false);

  const resultEl = $('#import-result');
  resultEl.innerHTML = '<span class="spinner"></span> 导入中（含事实提取）...';

  try {
    const r = await api('/pipeline/import', {
      method: 'POST',
      body: JSON.stringify({
        chapter_number: chNum,
        text: text,
        extract_facts: true,
        project_id: currentProject,
      }),
    });
    const obs = r.observations_extracted ? '已提取事实' : '未提取事实';
    resultEl.innerHTML = `<span style="color:var(--success)">第 ${r.chapter_number} 章导入成功，${obs}。当前进度：第 ${r.current_chapter} 章</span>`;
    toast('导入成功');
    loadChaptersPage();
    loadGeneratePage();
  } catch (e) {
    resultEl.innerHTML = `<span style="color:var(--danger)">导入失败: ${esc(e.message)}</span>`;
    toast('导入失败', false);
  }
}

async function importBatchChapters() {
  const startCh = parseInt($('#import-start-ch').value) || 1;
  const text = prompt(`批量导入：每章用 "第X章" 或空行分隔，从第 ${startCh} 章开始：`);
  if (!text) return;

  // Split by chapter markers
  const parts = text.split(/(?=第[一二三四五六七八九十百千\d]+章)/g).filter(s => s.trim().length >= 50);
  if (parts.length === 0) return toast('未检测到有效章节', false);

  const resultEl = $('#import-result');
  resultEl.innerHTML = `<span class="spinner"></span> 批量导入 ${parts.length} 章...`;

  const chapters = parts.map((part, i) => ({
    chapter_number: startCh + i,
    text: part.trim(),
    title: '',
    extract_facts: true,
  }));

  try {
    const r = await api('/pipeline/import/batch', {
      method: 'POST',
      body: JSON.stringify({ chapters, project_id: currentProject }),
    });
    resultEl.innerHTML = `<span style="color:var(--success)">成功导入 ${r.imported_count} 章，当前进度：第 ${r.current_chapter} 章</span>`;
    toast(`导入 ${r.imported_count} 章`);
    loadChaptersPage();
    loadGeneratePage();
  } catch (e) {
    resultEl.innerHTML = `<span style="color:var(--danger)">批量导入失败: ${esc(e.message)}</span>`;
    toast('批量导入失败', false);
  }
}

async function deleteChapter(chNum) {
  if (!confirm(`确定要删除第 ${chNum} 章吗？此操作不可撤销。`)) return;

  try {
    await api(`/projects/${currentProject}/chapters/${chNum}`, { method: 'DELETE' });
    toast('已删除第 ' + chNum + ' 章');
    cachedWorldState = null;  // 清除缓存，强制刷新世界状态
    loadChaptersPage();
  } catch (e) {
    toast('删除失败: ' + e.message, false);
  }
}

async function viewChapter(chNum) {
  try {
    document.querySelectorAll('.modal-overlay').forEach(el => el.remove());
    const ch = await api(`/projects/${currentProject}/chapters/${chNum}`);
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal" style="max-width:900px;max-height:90vh">
        <h3>第 ${chNum} 章 ${esc(ch.outline?.chapter_title || '')}</h3>
        <div class="tabs">
          <button class="tab-btn active" data-tab="text">正文</button>
          <button class="tab-btn" data-tab="outline">大纲</button>
          <button class="tab-btn" data-tab="eval">评估</button>
        </div>
        <div id="tab-text" class="tab-panel active">
          <textarea class="code-editor" id="ch-editor" style="min-height:400px;line-height:1.8">${esc(ch.final_text || '')}</textarea>
        </div>
        <div id="tab-outline" class="tab-panel">
          <pre style="background:var(--surface2);padding:12px;border-radius:var(--radius);font-size:0.8rem;max-height:400px;overflow:auto">${esc(JSON.stringify(ch.outline || {}, null, 2))}</pre>
        </div>
        <div id="tab-eval" class="tab-panel">
          <pre style="background:var(--surface2);padding:12px;border-radius:var(--radius);font-size:0.8rem;max-height:400px;overflow:auto">${esc(JSON.stringify(ch.evaluation || {}, null, 2))}</pre>
        </div>
        <div class="modal-actions">
          <button class="btn btn-outline" onclick="this.closest('.modal-overlay').remove()">关闭</button>
          <button class="btn btn-primary" id="save-ch-btn">保存修改</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    overlay.querySelectorAll('.tab-btn').forEach(btn => {
      btn.onclick = () => {
        overlay.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        overlay.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        overlay.querySelector(`#tab-${btn.dataset.tab}`).classList.add('active');
      };
    });
    overlay.querySelector('#save-ch-btn').onclick = async () => {
      const newText = overlay.querySelector('#ch-editor').value;
      try {
        await api(`/projects/${currentProject}/chapters/${chNum}`, {
          method: 'PUT', body: JSON.stringify({ text: newText }),
        });
        toast('已保存'); overlay.remove(); loadChaptersPage();
      } catch (e) { toast('保存失败: ' + e.message, false); }
    };
    overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };
  } catch (e) { toast('加载失败: ' + e.message, false); }
}

// ══════════════════════════════════════════
//  OUTLINE WINDOW MANAGEMENT
// ══════════════════════════════════════════
async function loadOutlines() {
  try {
    const r = await api(`/outline?project_id=${currentProject}`);
    const list = $('#outlines-list');
    if (!r.outlines.length) {
      list.innerHTML = '<p style="color:var(--text2);text-align:center;padding:16px">暂无大纲。点击「生成章节」时会自动生成，或点击「重新生成」手动创建。</p>';
      return;
    }
    const statusColors = { confirmed: 'badge-ok', pending: 'badge-info', rejected: 'badge-err' };
    const statusLabels = { confirmed: '已确认', pending: '待确认', rejected: '已驳回' };
    list.innerHTML = r.outlines.map(o => `
      <div style="padding:16px 20px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);border-left:3px solid ${o.status==='confirmed'?'var(--success)':o.status==='rejected'?'var(--danger)':'var(--primary)'}">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <div style="display:flex;align-items:center;gap:10px">
            <strong style="font-size:1rem">第 ${o.chapter_number} 章</strong>
            <span class="badge ${statusColors[o.status]||'badge-info'}">${statusLabels[o.status]||o.status}</span>
            ${o.emotional_direction ? `<span class="badge badge-warn">${esc(o.emotional_direction)}</span>` : ''}
          </div>
          <div style="display:flex;gap:6px">
            ${o.status !== 'confirmed' ? `<button class="btn btn-sm btn-outline" onclick="editOutline(${o.chapter_number})">编辑</button>` : ''}
            ${o.status !== 'confirmed' ? `<button class="btn btn-sm btn-outline" onclick="confirmOutline(${o.chapter_number})" style="color:var(--success)">确认</button>` : ''}
            ${o.status !== 'rejected' ? `<button class="btn btn-sm btn-outline" onclick="rejectOutline(${o.chapter_number})" style="color:var(--danger)">驳回</button>` : ''}
          </div>
        </div>
        <div style="font-size:0.9rem;margin-bottom:4px"><strong>目标：</strong>${esc(o.chapter_goal||'')}</div>
        ${o.core_conflict ? `<div style="font-size:0.85rem;color:var(--text-dim);margin-bottom:4px"><strong>冲突：</strong>${esc(o.core_conflict)}</div>` : ''}
        ${o.key_events?.length ? `<div style="font-size:0.85rem;color:var(--text-dim)"><strong>事件：</strong>${o.key_events.map(e=>esc(e)).join('、')}</div>` : ''}
        ${o.character_arcs?.length ? `<div style="font-size:0.85rem;color:var(--text-dim);margin-top:2px"><strong>角色弧：</strong>${o.character_arcs.map(a=>esc(a)).join('、')}</div>` : ''}
        ${o.notes ? `<div style="font-size:0.82rem;color:var(--text-muted);margin-top:6px;padding-top:6px;border-top:1px solid var(--border)">${esc(o.notes)}</div>` : ''}
      </div>
    `).join('');
  } catch (e) { toast('加载大纲失败: ' + e.message, false); }
}

async function confirmOutline(chNum) {
  try {
    await api(`/outline/${chNum}/confirm?project_id=${currentProject}`, { method: 'POST' });
    toast(`第 ${chNum} 章大纲已确认`);
    loadOutlines();
  } catch (e) { toast('确认失败: ' + e.message, false); }
}

async function rejectOutline(chNum) {
  if (!confirm(`驳回第 ${chNum} 章大纲？将标记为已驳回。`)) return;
  try {
    await api(`/outline/${chNum}/reject?project_id=${currentProject}`, { method: 'POST' });
    toast(`第 ${chNum} 章大纲已驳回`);
    loadOutlines();
  } catch (e) { toast('驳回失败: ' + e.message, false); }
}

async function editOutline(chNum) {
  try {
    const o = await api(`/outline/${chNum}?project_id=${currentProject}`);
    showModal(`编辑第 ${chNum} 章大纲`, `
      <div class="form-group"><label>核心目标</label><textarea id="m-goal" rows="2">${esc(o.chapter_goal||'')}</textarea></div>
      <div class="form-group"><label>核心冲突</label><textarea id="m-conflict" rows="2">${esc(o.core_conflict||'')}</textarea></div>
      <div class="form-group"><label>关键事件（每行一个）</label><textarea id="m-events" rows="3">${(o.key_events||[]).join('\n')}</textarea></div>
      <div class="form-group"><label>角色弧（每行一个）</label><textarea id="m-arcs" rows="2">${(o.character_arcs||[]).join('\n')}</textarea></div>
      <div class="form-group"><label>情绪走向</label><input id="m-mood" value="${esc(o.emotional_direction||'')}"></div>
      <div class="form-group"><label>备注</label><textarea id="m-notes" rows="2">${esc(o.notes||'')}</textarea></div>
    `, async (body) => {
      const parseLines = (el) => body.querySelector(el).value.split('\n').map(s=>s.trim()).filter(Boolean);
      await api(`/outline/${chNum}?project_id=${currentProject}`, {
        method: 'PUT',
        body: JSON.stringify({
          chapter_goal: body.querySelector('#m-goal').value,
          core_conflict: body.querySelector('#m-conflict').value,
          key_events: parseLines('#m-events'),
          character_arcs: parseLines('#m-arcs'),
          emotional_direction: body.querySelector('#m-mood').value,
          notes: body.querySelector('#m-notes').value,
        }),
      });
      toast('大纲已更新'); loadOutlines();
    });
  } catch (e) { toast('加载大纲失败: ' + e.message, false); }
}

async function regenerateOutlines() {
  if (!confirm('重新生成所有大纲？现有大纲将被覆盖。')) return;
  try {
    const r = await api(`/outline/generate?project_id=${currentProject}`, { method: 'POST' });
    toast(`已生成 ${r.outlines.length} 章大纲`);
    loadOutlines();
  } catch (e) { toast('生成失败: ' + e.message, false); }
}

// ══════════════════════════════════════════
//  WRITER WORKBENCH
// ══════════════════════════════════════════
let wbCurrentChapter = 0;

async function loadWorkbench() {
  try {
    const ws = await api(`/world?project_id=${currentProject}`);
    const sel = $('#wb-chapter-select');
    const total = ws.current_chapter || 0;
    sel.innerHTML = '<option value="0">选择章节...</option>';
    for (let i = 1; i <= total + 1; i++) {
      const opt = document.createElement('option');
      opt.value = i;
      opt.textContent = `第 ${i} 章${i > total ? '（新章节）' : ''}`;
      sel.appendChild(opt);
    }
    if (wbCurrentChapter > 0) sel.value = wbCurrentChapter;
  } catch (_) {}
}

async function loadWorkbenchContext() {
  const ch = parseInt($('#wb-chapter-select').value) || 0;
  if (!ch) return;
  wbCurrentChapter = ch;
  $('#wb-chapter-title').textContent = `第 ${ch} 章`;

  try {
    const ctx = await api('/workbench/chapter-context', {
      method: 'POST',
      body: JSON.stringify({ chapter_number: ch, project_id: currentProject }),
    });

    // Characters
    const charsDiv = $('#wb-characters');
    const chars = ctx.characters || {};
    if (Object.keys(chars).length) {
      charsDiv.innerHTML = Object.entries(chars).map(([name, c]) =>
        `<div class="wb-char-item"><strong>${esc(name)}</strong> <span class="badge ${c.status==='alive'?'badge-ok':'badge-err'}" style="font-size:0.65rem">${c.status}</span><p>${esc(c.description||'')} ${c.traits?'· '+esc(c.traits):''}</p></div>`
      ).join('');
    } else {
      charsDiv.innerHTML = '<p style="color:var(--text3)">暂无角色</p>';
    }

    // Foreshadowing
    const fsDiv = $('#wb-foreshadowing');
    const fs = ctx.foreshadowing || [];
    if (fs.length) {
      fsDiv.innerHTML = fs.map(f =>
        `<div class="wb-fs-item ${f.status==='resolved'?'resolved':''}"><span class="badge ${f.status==='resolved'?'badge-ok':'badge-info'}" style="font-size:0.6rem">${f.status}</span> ${esc(f.detail)}</div>`
      ).join('');
    } else {
      fsDiv.innerHTML = '<p style="color:var(--text3)">暂无伏笔</p>';
    }

    // Outline
    const outlineDiv = $('#wb-outline');
    if (ctx.outline) {
      const o = ctx.outline;
      outlineDiv.innerHTML = `
        <div style="margin-bottom:4px"><strong>目标：</strong>${esc(o.chapter_goal||'')}</div>
        ${o.core_conflict ? `<div style="margin-bottom:4px"><strong>冲突：</strong>${esc(o.core_conflict)}</div>` : ''}
        ${o.key_events?.length ? `<div><strong>事件：</strong>${o.key_events.map(e=>esc(e)).join('、')}</div>` : ''}
      `;
    } else {
      outlineDiv.innerHTML = '<p style="color:var(--text3)">暂无大纲</p>';
    }

    // Summaries
    const sumDiv = $('#wb-summaries');
    const sums = ctx.recent_summaries || [];
    if (sums.length) {
      sumDiv.innerHTML = sums.map((s, i) =>
        `<div style="margin-bottom:4px;font-size:0.75rem"><strong>第${ctx.chapter_number - sums.length + i}章：</strong>${esc(s)}</div>`
      ).join('');
    } else {
      sumDiv.innerHTML = '<p style="color:var(--text3)">暂无摘要</p>';
    }

    // Plot threads
    const threadsDiv = $('#wb-threads');
    const threads = ctx.plot_threads || [];
    if (threads.length) {
      threadsDiv.innerHTML = threads.map(t =>
        `<div style="margin-bottom:3px"><span class="badge badge-info" style="font-size:0.6rem">${esc(t.type)}</span> <strong>${esc(t.name)}</strong><br><span style="font-size:0.72rem;color:var(--text2)">${esc(t.description||'')}</span></div>`
      ).join('');
    } else {
      threadsDiv.innerHTML = '<p style="color:var(--text3)">暂无线程</p>';
    }
  } catch (e) { toast('加载上下文失败: ' + e.message, false); }
}

async function wbLoadChapter() {
  if (!wbCurrentChapter) return toast('请先选择章节', false);
  try {
    const ch = await api(`/projects/${currentProject}/chapters/${wbCurrentChapter}`);
    $('#wb-editor').value = ch.final_text || '';
    toast('章节已加载');
  } catch (_) {
    // Chapter doesn't exist yet, that's fine
    $('#wb-editor').value = '';
    toast('新章节，开始写作吧');
  }
}

async function wbSaveAndObserve() {
  if (!wbCurrentChapter) return toast('请先选择章节', false);
  const text = $('#wb-editor').value;
  if (text.length < 50) return toast('正文太短（至少50字）', false);

  try {
    const r = await api('/workbench/save-and-observe', {
      method: 'POST',
      body: JSON.stringify({ chapter_number: wbCurrentChapter, text, project_id: currentProject }),
    });
    toast('已保存并提取事实');
    // Refresh context to show updated data
    loadWorkbenchContext();
  } catch (e) { toast('保存失败: ' + e.message, false); }
}

async function wbRunReview() {
  const text = $('#wb-editor').value;
  if (text.length < 50) return toast('正文太短（至少50字）', false);

  const reviewDiv = $('#wb-review-content');
  reviewDiv.innerHTML = '<div style="text-align:center;padding:20px"><span class="spinner"></span> 审校中...</div>';

  try {
    const r = await api('/workbench/run-review', {
      method: 'POST',
      body: JSON.stringify({ chapter_number: wbCurrentChapter, text, project_id: currentProject }),
    });
    const ev = r.evaluation;
    const score = ev.total_score || 0;
    const passed = ev.pass || false;
    const antiAi = ev.anti_ai_score;

    let html = `<div style="margin-bottom:12px">
      <span class="score-badge ${passed?'pass':'fail'}">${score}/70 ${passed?'通过':'需修改'}</span>
      ${antiAi!=null?` <span class="score-badge ${antiAi>=60?'pass':'fail'}" style="font-size:0.75rem">AI味 ${antiAi}/100</span>`:''}
    </div>`;

    if (ev.issues?.length) {
      html += '<div style="margin-bottom:12px"><strong style="font-size:0.82rem">问题</strong>';
      ev.issues.forEach(i => {
        html += `<div class="issue-item ${i.severity||'medium'}" style="font-size:0.78rem">[${esc(i.severity||'')}] ${esc(i.category||'')}: ${esc(i.description||'')}<br><small style="color:var(--text2)">建议: ${esc(i.suggestion||'')}</small></div>`;
      });
      html += '</div>';
    }

    if (ev.highlights?.length) {
      html += `<div style="margin-bottom:12px"><strong style="font-size:0.82rem">亮点</strong><ul style="margin:4px 0;padding-left:16px;font-size:0.78rem">${ev.highlights.map(h=>`<li>${esc(h)}</li>`).join('')}</ul></div>`;
    }

    if (ev.anti_ai_learning?.length) {
      html += '<details style="margin-bottom:12px"><summary style="cursor:pointer;color:var(--primary);font-size:0.82rem;font-weight:600">📖 去AI味学习</summary>';
      ev.anti_ai_learning.forEach(ex => {
        html += `<div style="margin:6px 0;padding:8px;background:var(--surface2);border-radius:var(--radius-sm);border-left:2px solid var(--warning)">
          <div style="font-size:0.78rem;font-weight:600">${esc(ex.type==='fatigue_word'?'🔤 '+ex.keyword:'📐 句式问题')} <span class="badge badge-warn" style="font-size:0.6rem">${ex.count}次</span></div>
          <div style="font-size:0.75rem;color:var(--text2);margin:4px 0">${esc(ex.diagnosis)}</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:0.72rem">
            <div style="background:var(--danger-dim);padding:4px;border-radius:3px"><strong style="color:var(--danger)">✗</strong> ${esc(ex.original)}</div>
            <div style="background:var(--success-dim);padding:4px;border-radius:3px"><strong style="color:var(--success)">✓</strong> ${esc(ex.improved)}</div>
          </div>
          <div style="font-size:0.72rem;color:var(--primary);margin-top:4px">💡 ${esc(ex.principle)}</div>
        </div>`;
      });
      html += '</details>';
    }

    reviewDiv.innerHTML = html;
  } catch (e) {
    reviewDiv.innerHTML = `<div style="color:var(--danger);padding:12px">审校失败: ${esc(e.message)}</div>`;
  }
}

// ══════════════════════════════════════════
//  BOOK DISTILLATION
// ══════════════════════════════════════════
let currentDistillJobId = null;

function getDistillModelOverride() {
  const provider = $('#distill-provider')?.value || '';
  const model = $('#distill-model')?.value?.trim() || '';
  const temp = $('#distill-temp')?.value;
  const tokens = $('#distill-tokens')?.value;
  const apikey = $('#distill-apikey')?.value?.trim() || '';
  const override = {};
  if (provider) override.provider = provider;
  if (model) override.model_name = model;
  if (temp) override.temperature = parseFloat(temp);
  if (tokens) override.max_tokens = parseInt(tokens);
  if (apikey) override.api_key = apikey;
  return Object.keys(override).length ? override : null;
}

function populateDistillProviders(providers) {
  const sel = $('#distill-provider');
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = '<option value="">使用全局配置</option>';
  providers.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.name;
    opt.textContent = `${p.name} (${p.base_url})`;
    sel.appendChild(opt);
  });
  sel.value = current;
}

async function uploadBook() {
  const fi = $('#book-file'), ta = $('#book-text'), info = $('#upload-info');
  const fd = new FormData();
  if (fi.files.length) fd.append('file', fi.files[0]);
  else if (ta.value.trim().length >= 100) fd.append('text', ta.value.trim());
  else return toast('请上传或粘贴至少 100 字', false);
  info.textContent = '上传中...';
  try {
    const r = await fetch(`${API}/distill/upload`, { method: 'POST', body: fd }).then(r => r.json());
    currentDistillJobId = r.job_id; info.textContent = `${r.text_length} 字，${r.chunk_count} 段`; toast('上传成功'); startAnalysis();
  } catch (e) { info.textContent = ''; toast('失败: ' + e.message, false); }
}

async function startAnalysis() {
  if (!currentDistillJobId) return;
  $('#distill-progress').style.display = 'block'; $('#distill-results').style.display = 'none';
  const bar = $('#progress-bar'), log = $('#progress-log');
  bar.style.width = '0%'; log.innerHTML = '';
  let pollInterval = 1000;
  let pollStopped = false;
  function schedulePoll() {
    if (pollStopped) return;
    pollTimer = setTimeout(async () => {
      try { const j = await fetch(`${API}/distill/${currentDistillJobId}`).then(r => r.json());
        log.innerHTML = (j.progress||[]).map(p => `> ${esc(p.message)}`).join(''); log.scrollTop = log.scrollHeight;
        if (j.progress?.length) { const l = j.progress[j.progress.length-1]; const p = Math.round(l.current/l.total*100); bar.style.width = p+'%'; bar.textContent = p+'%'; }
        pollInterval = Math.min(pollInterval * 1.5, 5000);
      } catch(_){}
      schedulePoll();
    }, pollInterval);
  }
  schedulePoll();
  try {
    const modelOverride = getDistillModelOverride();
    const body = modelOverride ? JSON.stringify(modelOverride) : undefined;
    const headers = body ? { 'Content-Type': 'application/json' } : {};
    const r = await api(`/distill/${currentDistillJobId}/analyze`, { method: 'POST', headers, body });
    pollStopped = true; clearTimeout(pollTimer); bar.style.width = '100%'; bar.textContent = '100%';
    toast('分析完成');
    const a = r.analysis;
    $('#analysis-summary').innerHTML = `<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px"><div><strong>类型:</strong> ${esc(a.genre||'')}</div><div><strong>书名:</strong> ${esc(a.book_title||'')}</div></div><div style="margin-top:8px"><strong>风格:</strong> ${esc(a.overall_style||'')}</div>`;
    $('#distill-results').style.display = 'block';
    $('#skills-preview').innerHTML = `<div style="text-align:center;padding:20px"><button class="btn btn-success" onclick="generateSkills()" style="padding:12px 32px">生成全套 Skill</button></div>`;
  } catch (e) { pollStopped = true; clearTimeout(pollTimer); toast('分析失败: ' + e.message, false); }
}

async function generateSkills() {
  if (!currentDistillJobId) return;
  $('#skills-preview').innerHTML = '<div style="text-align:center;padding:20px"><span class="spinner"></span> 生成中...</div>';
  const title = prompt('书名:', '蒸馏作品') || '蒸馏作品';
  try {
    const modelOverride = getDistillModelOverride();
    const body = modelOverride ? JSON.stringify(modelOverride) : undefined;
    const headers = body ? { 'Content-Type': 'application/json' } : {};
    const r = await api(`/distill/${currentDistillJobId}/generate?book_title=${encodeURIComponent(title)}`, { method: 'POST', headers, body });
    $('#skills-preview').innerHTML = Object.keys(r.skills).map(st => `<div class="card" style="margin:4px 0"><h4 style="color:var(--primary)">${esc(st)}</h4><p style="font-size:0.85rem;color:var(--text2)">${esc(r.skills[st].description)}</p></div>`).join('');
    toast('生成完成');
  } catch (e) { $('#skills-preview').innerHTML = `<div style="color:var(--danger)">${esc(e.message)}</div>`; }
}

async function installDistilledSkills() {
  if (!currentDistillJobId) return;
  const prefix = prompt('命名前缀:', 'distilled') || 'distilled';
  try {
    const r = await api(`/distill/${currentDistillJobId}/install?slug_prefix=${encodeURIComponent(prefix)}`, { method: 'POST' });
    $('#distill-installed').style.display = 'block';
    $('#install-result').innerHTML = r.installed.map(i => i.error ? `<div style="color:var(--danger)">${esc(i.skill_type)}: ${esc(i.error)}</div>` : `<div style="color:var(--success)">${esc(i.skill_type)}/${esc(i.slug)} ✓</div>`).join('');
    toast('安装完成'); loadSkills();
  } catch (e) { toast('失败: ' + e.message, false); }
}

// ══════════════════════════════════════════
//  SKILLS
// ══════════════════════════════════════════
let skillTypes = [];
async function loadSkills() {
  try {
    const [types, s] = await Promise.all([api('/skills/types'), api('/skills')]);
    skillTypes = types;
    renderSkillGroups(s);
  } catch (e) { toast('失败: ' + e.message, false); }
}
function renderSkillGroups(skills) {
  const container = $('#skills-groups'), em = $('#skills-empty');
  if (!skills.length) { container.innerHTML = ''; em.style.display = 'block'; return; }
  em.style.display = 'none';

  // Group by skill_type
  const groups = {};
  for (const s of skills) {
    if (!groups[s.skill_type]) groups[s.skill_type] = [];
    groups[s.skill_type].push(s);
  }
  const typeLabels = { editor: '📝 编辑', writer: '✍️ 写手', librarian: '📚 图书管理员', strategist: '🎯 策略师', prophet: '🔮 大纲师' };

  let html = '';
  for (const [type, items] of Object.entries(groups)) {
    const label = typeLabels[type] || type;
    html += `<div class="card" style="margin-bottom:16px">
      <div class="card-header" style="cursor:pointer" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'; this.querySelector('.toggle-icon').textContent=this.nextElementSibling.style.display==='none'?'▸':'▾'">
        <h3><span class="toggle-icon" style="margin-right:8px;font-size:0.8em">▾</span>${label} <span style="color:var(--text-dim);font-size:0.7em;font-weight:normal">(${items.length})</span></h3>
      </div>
      <div style="padding:0 20px 16px">
        <table style="width:100%"><thead><tr><th>名称</th><th>描述</th><th>版本</th><th>操作</th></tr></thead><tbody>`;
    for (const s of items) {
      const isBase = s.version === 'base';
      const tag = isBase ? '<span class="badge badge-ok" style="font-size:0.7rem;margin-left:6px">基础</span>' : '<span class="badge badge-info" style="font-size:0.7rem;margin-left:6px">蒸馏</span>';
      html += `<tr>
        <td><strong>${esc(s.display_name)}</strong>${tag}<br><small style="color:var(--text2)">${esc(s.slug)}</small></td>
        <td style="font-size:0.8rem;color:var(--text2);max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.description).substring(0,80)}</td>
        <td>${s.version}</td>
        <td><button class="btn btn-sm btn-outline" onclick="editSkill('${s.skill_type}','${s.slug}')">编辑</button> ${isBase ? '' : `<button class="btn btn-sm btn-danger" onclick="deleteSkill('${s.skill_type}','${s.slug}')">删除</button>`}</td>
      </tr>`;
    }
    html += '</tbody></table></div></div>';
  }
  // Add create button at the bottom
  html += '<div style="text-align:center;margin-top:16px"><button class="btn btn-primary btn-sm" onclick="showCreateSkillModal()">+ 创建新技能</button></div>';
  container.innerHTML = html;
}
function showCreateSkillModal() {
  const opts = skillTypes.map(t => `<option value="${t.type}">${t.display_name}</option>`).join('');
  showModal('创建 Skill', `<div class="form-row"><div class="form-group"><label>类型</label><select id="m-type">${opts}</select></div><div class="form-group"><label>Slug</label><input id="m-slug"></div></div><div class="form-group"><label>名称</label><input id="m-name"></div><div class="form-group"><label>Prompt</label><textarea id="m-prompt"></textarea></div>`, async b => {
    await api('/skills', { method:'POST', body: JSON.stringify({ skill_type: b.querySelector('#m-type').value, slug: b.querySelector('#m-slug').value||undefined, display_name: b.querySelector('#m-name').value||undefined, prompt_content: b.querySelector('#m-prompt').value||undefined }) });
    toast('已创建'); loadSkills();
  });
}
async function deleteSkill(t,s) { if(!confirm(`删除 ${t}/${s}?`)) return; await api(`/skills/${t}/${s}`,{method:'DELETE'}); toast('已删除'); loadSkills(); }
async function editSkill(t,s) { try { const d = await api(`/skills/${t}/${s}`); showSkillEditor(t,s,d); } catch(e) { toast(e.message, false); } }
function showSkillEditor(type, slug, detail) {
  document.querySelectorAll('.modal-overlay').forEach(el => el.remove());
  const f = detail.files;
  const o = document.createElement('div'); o.className = 'modal-overlay';
  o.innerHTML = `<div class="modal" style="max-width:900px;max-height:90vh"><h3>${type}/${slug}</h3><div class="tabs"><button class="tab-btn active" data-tab="prompt">prompt.md</button><button class="tab-btn" data-tab="config">config.yaml</button><button class="tab-btn" data-tab="samples">samples.json</button><button class="tab-btn" data-tab="agent">agent.py</button></div><div id="tab-prompt" class="tab-panel active"><textarea class="code-editor" id="ed-prompt" style="min-height:300px">${esc(f['prompt.md']||'')}</textarea></div><div id="tab-config" class="tab-panel"><textarea class="code-editor" id="ed-config" style="min-height:300px">${esc(f['config.yaml']||'')}</textarea></div><div id="tab-samples" class="tab-panel"><textarea class="code-editor" id="ed-samples" style="min-height:300px">${esc(f['samples.json']||'[]')}</textarea></div><div id="tab-agent" class="tab-panel"><textarea class="code-editor" id="ed-agent" style="min-height:300px">${esc(f['agent.py']||'')}</textarea></div><div class="modal-actions"><button class="btn btn-outline" onclick="this.closest('.modal-overlay').remove()">关闭</button><button class="btn btn-primary" id="save-sk-btn">保存</button></div></div>`;
  document.body.appendChild(o);
  o.querySelectorAll('.tab-btn').forEach(b => { b.onclick = () => { o.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active')); o.querySelectorAll('.tab-panel').forEach(x=>x.classList.remove('active')); b.classList.add('active'); o.querySelector(`#tab-${b.dataset.tab}`).classList.add('active'); }; });
  o.querySelector('#save-sk-btn').onclick = async () => {
    for (const u of [{file:'prompt.md',el:'#ed-prompt'},{file:'config.yaml',el:'#ed-config'},{file:'samples.json',el:'#ed-samples'},{file:'agent.py',el:'#ed-agent'}]) {
      const c = o.querySelector(u.el).value; if (c !== (f[u.file]||'')) await fetch(`${API}/skills/${type}/${slug}/files/${u.file}`,{method:'POST',headers:{'Content-Type':'text/plain'},body:c});
    }
    toast('已保存'); o.remove(); loadSkills();
  };
  o.onclick = e => { if(e.target===o) o.remove(); };
}

// ══════════════════════════════════════════
//  WORLD STATE
// ══════════════════════════════════════════
async function loadWorldState() {
  try {
    const ws = cachedWorldState || await api(`/world?project_id=${currentProject}`);
    cachedWorldState = ws;
    $('#world-setting').value = ws.world_setting || '';
    $('#current-chapter').value = ws.current_chapter || 0;
    $('#author-intent').value = ws.author_intent || '';
    $('#current-focus').value = ws.current_focus || '';

    // Plan B: Render Templates and pass to character renderer
    renderSettingTemplates(ws.setting_templates || {});
    renderCharacters(ws.characters || {}, ws.setting_templates || {});
    renderForeshadowing(ws.foreshadowing_pool);
    renderForeshadowingTracker(ws.foreshadowing_pool);

    // Parallel fetch remaining data
    const [rels, threads, tropes] = await Promise.all([
      api(`/world/relationships?project_id=${currentProject}`),
      api(`/world/plot-threads?project_id=${currentProject}`),
      api(`/world/tropes?project_id=${currentProject}`),
    ]);
    renderRelationships(rels);
    renderPlotThreads(threads);
    renderTropes(tropes);
  } catch (e) { toast('失败: ' + e.message, false); }
}

function renderSettingTemplates(templates) {
  const c = $('#setting-templates-list');
  if (!c) return;
  if (!Object.keys(templates).length) { c.innerHTML = '<p style="color:var(--text-muted)">暂无自定义规则维度</p>'; return; }
  c.innerHTML = Object.entries(templates).map(([k, v]) => `
    <div class="card" style="padding:16px; margin:0; background:rgba(255,255,255,0.02)">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:8px">
        <strong style="color:var(--primary-hover)">${esc(k)}</strong>
        <div style="display:flex; gap:4px">
          <button class="btn btn-sm btn-outline" style="padding:4px 8px" onclick="showAddSettingTemplateModal('${esc(k)}','${esc(v)}')">✎</button>
          <button class="btn btn-sm btn-outline" style="padding:4px 8px; color:var(--danger)" onclick="deleteSettingTemplate('${esc(k)}')">&times;</button>
        </div>
      </div>
      <p style="font-size:0.85rem; color:var(--text-dim)">${esc(v)}</p>
    </div>
  `).join('');
}

function showAddSettingTemplateModal(oldKey='', oldVal='') {
  showModal(oldKey ? '编辑规则维度' : '添加规则维度', `
    <div class="form-group"><label>维度名称 (如: 境界)</label><input id="m-key" value="${esc(oldKey)}" ${oldKey?'readonly':''}></div>
    <div class="form-group"><label>规则说明 (决定 AI 如何理解该维度)</label><textarea id="m-val" rows="3">${esc(oldVal)}</textarea></div>
  `, async b => {
    const key = b.querySelector('#m-key').value.trim();
    const val = b.querySelector('#m-val').value.trim();
    if(!key || !val) throw new Error('必填项不能为空');
    
    // We update the whole world state or a specific endpoint if exists
    const ws = await api(`/world?project_id=${currentProject}`);
    const templates = ws.setting_templates || {};
    templates[key] = val;
    
    await api(`/world?project_id=${currentProject}`, {
      method: 'PUT',
      body: JSON.stringify({ setting_templates: templates })
    });
    
    toast('规则已更新'); loadWorldState();
  });
}

async function deleteSettingTemplate(key) {
  if(!confirm(`删除规则 "${key}"? 角色中对应的设定也会失去参考。`)) return;
  const ws = await api(`/world?project_id=${currentProject}`);
  const templates = ws.setting_templates || {};
  delete templates[key];
  await api(`/world?project_id=${currentProject}`, {
    method: 'PUT',
    body: JSON.stringify({ setting_templates: templates })
  });
  toast('已删除'); loadWorldState();
}

async function saveGovernance() {
  try {
    await api(`/world/governance?project_id=${currentProject}`, {
      method: 'PUT',
      body: JSON.stringify({
        author_intent: $('#author-intent').value,
        current_focus: $('#current-focus').value,
      }),
    });
    toast('创作方向已保存');
  } catch (e) { toast('保存失败: ' + e.message, false); }
}
function renderCharacters(chars, templates = {}) {
  const c = $('#characters-list');
  if (!chars || !Object.keys(chars).length) { c.innerHTML = '<p style="color:var(--text-muted)">暂无角色记录</p>'; return; }
  
  c.innerHTML = Object.entries(chars).map(([n, i]) => {
    const tagHtml = (i.tags || []).map(t => `<span class="char-tag">${esc(t)}</span>`).join('');
    
    // Render custom attributes that match current templates
    const attrHtml = Object.entries(i.custom_settings || {})
      .filter(([k]) => templates[k]) // Only show if template still exists
      .map(([k, v]) => `
        <div class="char-attr-item">
          <span class="char-attr-label">${esc(k)}</span>
          <span class="char-attr-val">${esc(v)}</span>
        </div>
      `).join('');

    return `
      <div class="char-card fade-in">
        <div class="char-card-header">
          <span class="char-name">${esc(n)}</span>
          <div style="display:flex; gap:8px">
            <button class="btn btn-sm btn-outline" style="padding:4px 8px" onclick="editCharacter('${esc(n)}')">✎</button>
            <button class="btn btn-sm btn-outline" style="padding:4px 8px; color:var(--danger)" onclick="deleteCharacter('${esc(n)}')">&times;</button>
          </div>
        </div>
        <p style="font-size:0.9rem; color:var(--text-dim); margin-bottom:8px">${esc(i.description || '暂无描述')}</p>
        <div style="font-size:0.8rem; color:var(--primary-hover); margin-bottom:12px">性格: ${esc(i.traits || '未设定')}</div>
        
        ${tagHtml ? `<div class="char-tag-list">${tagHtml}</div>` : ''}
        
        ${attrHtml ? `<div class="char-attr-grid">${attrHtml}</div>` : ''}
      </div>
    `;
  }).join('');
}

async function editCharacter(name) {
  const ws = await api(`/world?project_id=${currentProject}`);
  const ch = ws.characters[name];
  if(ch) showAddCharacterModal(ch, ws.setting_templates || {});
}

function showAddCharacterModal(existingChar = null, templates = {}) {
  const isEdit = !!existingChar;
  
  // Prepare dynamic inputs for custom settings
  const customInputs = Object.entries(templates).map(([k, desc]) => `
    <div class="form-group">
      <label>${esc(k)} <small style="font-weight:normal; color:var(--text-muted)">(${esc(desc)})</small></label>
      <input class="m-custom-attr" data-key="${esc(k)}" value="${esc(existingChar?.custom_settings?.[k] || '')}" placeholder="输入该角色的 ${esc(k)}...">
    </div>
  `).join('');

  showModal(isEdit ? `编辑角色: ${existingChar.name}` : '添加新角色', `
    <div class="form-group"><label>姓名</label><input id="m-name" value="${esc(existingChar?.name || '')}" ${isEdit?'readonly':''}></div>
    <div class="form-group"><label>身份描述</label><input id="m-desc" value="${esc(existingChar?.description || '')}" placeholder="如：落魄世家子弟"></div>
    <div class="form-group"><label>核心性格标签 (traits)</label><input id="m-traits" value="${esc(existingChar?.traits || '')}" placeholder="如：坚毅、果守、重感情"></div>
    <div class="form-group"><label>印象标签 (tags, 逗号分隔)</label><input id="m-tags" value="${esc((existingChar?.tags || []).join('，'))}" placeholder="如：腹黑，毒舌，隐藏大佬"></div>
    
    ${customInputs ? `<div style="margin-top:20px; padding-top:20px; border-top:1px solid var(--border)">
      <h4 style="font-size:0.9rem; margin-bottom:12px; color:var(--text-dim)">世界规则设定</h4>
      ${customInputs}
    </div>` : ''}
  `, async b => {
    const name = b.querySelector('#m-name').value.trim();
    if(!name) throw new Error('姓名不能为空');
    
    const tags = b.querySelector('#m-tags').value.split(/[，,]/).map(s => s.trim()).filter(Boolean);
    const custom_settings = {};
    b.querySelectorAll('.m-custom-attr').forEach(input => {
      custom_settings[input.dataset.key] = input.value.trim();
    });

    const payload = {
      name,
      description: b.querySelector('#m-desc').value.trim(),
      traits: b.querySelector('#m-traits').value.trim(),
      tags,
      custom_settings
    };

    await api(`/world/characters?project_id=${currentProject}`, {
      method: isEdit ? 'PUT' : 'POST',
      body: JSON.stringify(payload)
    });
    
    toast(isEdit ? '已更新' : '已添加'); loadWorldState();
  });
}
function showAddRelationshipModal() { showModal('添加关系', `<div class="form-group"><label>角色A</label><input id="m-c1"></div><div class="form-group"><label>角色B</label><input id="m-c2"></div><div class="form-group"><label>关系</label><input id="m-type" placeholder="师徒/朋友/敌对"></div><div class="form-group"><label>描述</label><input id="m-desc"></div>`, async b => { await api(`/world/relationships?project_id=${currentProject}`,{method:'POST',body:JSON.stringify({char1:b.querySelector('#m-c1').value,char2:b.querySelector('#m-c2').value,relation_type:b.querySelector('#m-type').value,description:b.querySelector('#m-desc').value})}); toast('已添加'); loadWorldState(); }); }
function showAddPlotThreadModal() { showModal('添加情节线', `<div class="form-group"><label>名称</label><input id="m-name"></div><div class="form-group"><label>类型</label><select id="m-type"><option value="main">主线</option><option value="subplot">支线</option><option value="romance">感情线</option></select></div><div class="form-group"><label>描述</label><textarea id="m-desc"></textarea></div>`, async b => { await api(`/world/plot-threads?project_id=${currentProject}`,{method:'POST',body:JSON.stringify({name:b.querySelector('#m-name').value,thread_type:b.querySelector('#m-type').value,description:b.querySelector('#m-desc').value})}); toast('已添加'); loadWorldState(); }); }
function showAddForeshadowModal() { showModal('添加伏笔', `<div class="form-group"><label>内容</label><input id="m-detail"></div><div class="form-group"><label>章节</label><input id="m-ch" type="number" value="1"></div>`, async b => { await api(`/world/foreshadowing?project_id=${currentProject}`,{method:'POST',body:JSON.stringify({detail:b.querySelector('#m-detail').value,related_chapter:parseInt(b.querySelector('#m-ch').value)})}); toast('已添加'); loadWorldState(); }); }
function showAddTropeModal() { showModal('记录桥段', `<div class="form-group"><label>桥段</label><input id="m-trope" placeholder="越级战斗"></div>`, async b => { await api(`/world/tropes?project_id=${currentProject}`,{method:'POST',body:JSON.stringify({trope:b.querySelector('#m-trope').value})}); toast('已记录'); loadWorldState(); }); }
async function deleteCharacter(n) { if(!confirm(`删除 ${n}?`)) return; try { await api(`/world/characters/${n}?project_id=${currentProject}`,{method:'DELETE'}); toast('已删除'); loadWorldState(); } catch(e) { toast('删除失败: '+e.message, false); } }

function renderRelationships(rels) {
  const tb = $('#relationships-table tbody');
  if (!tb) return;
  const entries = Object.entries(rels || {});
  if (!entries.length) { tb.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted);text-align:center;padding:20px">暂无关系记录</td></tr>'; return; }
  tb.innerHTML = entries.map(([k, r]) => `<tr><td>${esc(r.char1||'')}</td><td><span class="badge badge-info">${esc(r.relation_type||'')}</span></td><td>${esc(r.char2||'')}</td><td style="font-size:0.85rem;color:var(--text-dim)">${esc(r.description||'')}</td><td><button class="btn btn-sm btn-outline" style="color:var(--danger)" onclick="deleteRelationship('${esc(k)}')">&times;</button></td></tr>`).join('');
}

async function deleteRelationship(key) {
  if(!confirm('删除该关系?')) return;
  try { await api(`/world/relationships/${encodeURIComponent(key)}?project_id=${currentProject}`, {method:'DELETE'}); toast('已删除'); loadWorldState(); } catch(e) { toast('删除失败: '+e.message, false); }
}

function renderPlotThreads(threads) {
  const c = $('#plot-threads-list');
  if (!c) return;
  if (!threads || !threads.length) { c.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px">暂无情节线</p>'; return; }
  const typeColors = {main:'badge-ok', subplot:'badge-info', romance:'badge-warn'};
  c.innerHTML = threads.map(t => `<div style="padding:10px;background:rgba(255,255,255,0.02);border:1px solid var(--border);border-radius:var(--radius-sm);margin-bottom:6px;display:flex;justify-content:space-between;align-items:center"><div><span class="badge ${typeColors[t.type]||'badge-info'}" style="font-size:0.65rem">${esc(t.type||'')}</span> <strong>${esc(t.name||'')}</strong><br><span style="font-size:0.82rem;color:var(--text-dim)">${esc(t.description||'')}</span></div><span class="badge ${t.status==='active'?'badge-ok':'badge-err'}" style="font-size:0.6rem">${esc(t.status||'')}</span></div>`).join('');
}

function renderForeshadowing(pool) {
  const tb = $('#foreshadowing-table tbody');
  if (!tb) return;
  if (!pool || !pool.length) { tb.innerHTML = '<tr><td colspan="4" style="color:var(--text-muted);text-align:center;padding:20px">暂无伏笔</td></tr>'; return; }
  tb.innerHTML = pool.map((f, i) => `<tr><td style="font-size:0.88rem">${esc(f.detail||'')}</td><td>第 ${f.planted_chapter||0} 章</td><td><select class="select-styled" style="padding:4px 8px;font-size:0.8rem" onchange="updateForeshadowStatus(${i},this.value)"><option value="pending" ${f.status==='pending'?'selected':''}>待回收</option><option value="resolved" ${f.status==='resolved'?'selected':''}>已回收</option><option value="invalid" ${f.status==='invalid'?'selected':''}>已废弃</option></select></td><td><button class="btn btn-sm btn-outline" style="color:var(--danger)" onclick="deleteForeshadowing(${i})">&times;</button></td></tr>`).join('');
}

async function deleteForeshadowing(idx) {
  if(!confirm('删除该伏笔?')) return;
  try { await api(`/world/foreshadowing/${idx}?project_id=${currentProject}`, {method:'DELETE'}); toast('已删除'); loadWorldState(); } catch(e) { toast('删除失败: '+e.message, false); }
}

function renderTropes(tropes) {
  // Tropes are rendered inline in the world page if container exists
  let c = $('#tropes-list');
  if (!c) return;
  if (!tropes || !tropes.length) { c.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:16px">暂无记录的桥段</p>'; return; }
  c.innerHTML = tropes.map((t, i) => `<span class="char-tag" style="cursor:pointer" onclick="deleteTrope(${i})" title="点击删除">${esc(t)} &times;</span>`).join(' ');
}

async function deleteTrope(idx) {
  try { await api(`/world/tropes/${idx}?project_id=${currentProject}`, {method:'DELETE'}); toast('已删除'); loadWorldState(); } catch(e) { toast('删除失败: '+e.message, false); }
}
async function updateForeshadowStatus(i,s) { await api(`/world/foreshadowing/${i}/status?status=${s}&project_id=${currentProject}`,{method:'PUT'}); }
async function saveWorldSetting() { try { await api(`/world?project_id=${currentProject}`,{method:'PUT',body:JSON.stringify({world_setting:$('#world-setting').value,current_chapter:parseInt($('#current-chapter').value)||0})}); cachedWorldState = null; toast('已保存'); } catch(e) { toast('保存失败: '+e.message, false); } }

// ══════════════════════════════════════════
//  LLM CONFIG (with edit support)
// ══════════════════════════════════════════
async function loadLLMSettings() {
  try { const d = await api('/llm/settings'); renderProviders(d.providers); renderRoutes(d.role_routing, d.default, d.active_skills || []); populateDistillProviders(d.providers); } catch(e) { toast(e.message, false); }
}
function renderProviders(providers) {
  $('#providers-table tbody').innerHTML = providers.map(p => `<tr><td><strong>${esc(p.name)}</strong></td><td style="font-family:monospace;font-size:0.8rem">${esc(p.base_url)}</td><td><code>${esc(p.api_key_env)}</code></td><td>${p.has_key?'<span class="badge badge-ok">✓</span>':'<span class="badge badge-err">✗</span>'}</td><td><button class="btn btn-sm btn-outline" onclick="editProvider('${esc(p.name)}')">编辑</button> <button class="btn btn-sm btn-outline" onclick="testProvider('${esc(p.name)}')">测试</button> <button class="btn btn-sm btn-danger" onclick="deleteProvider('${esc(p.name)}')">删除</button></td></tr>`).join('');
}
function renderRoutes(routes, def, activeSkills) {
  const skillMap = {};
  for (const s of activeSkills) {
    const rn = s.role_name || s.slug;
    if (!skillMap[rn]) skillMap[rn] = [];
    skillMap[rn].push(s.display_name || s.slug);
  }
  const baseRoles = routes.filter(r => !r.role_name.startsWith('distilled-'));
  const distilledRoles = routes.filter(r => r.role_name.startsWith('distilled-'));

  function routeRow(r, isDefault) {
    const skills = skillMap[r.role_name] || [];
    const skillBadge = skills.length > 0
      ? skills.map(s => `<span class="badge badge-ok" style="margin:1px;font-size:0.7rem">${esc(s)}</span>`).join(' ')
      : '<span style="color:var(--text-dim);font-size:0.8rem">-</span>';
    const editOnclick = isDefault ? 'editDefaultRoute()' : `editRoute('${esc(r.role_name)}')`;
    const editBtn = `<button class="btn btn-sm btn-outline" onclick="${editOnclick}">编辑</button>`;
    const delBtn = isDefault ? '' : `<button class="btn btn-sm btn-danger" onclick="deleteRoute('${esc(r.role_name)}')">删除</button>`;
    return `<tr><td><strong>${esc(r.role_name)}</strong></td><td>${esc(r.provider)}</td><td><code>${esc(r.model_name)}</code></td><td>${r.temperature}</td><td>${r.max_tokens}</td><td>${skillBadge}</td><td>${editBtn} ${delBtn}</td></tr>`;
  }

  function groupCard(title, icon, routes, isDefaultGroup) {
    if (!routes.length && !isDefaultGroup) return '';
    const items = isDefaultGroup ? [routes] : routes;
    return `<div class="card" style="margin-bottom:16px">
      <div class="card-header" style="cursor:pointer" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'; this.querySelector('.toggle-icon').textContent=this.nextElementSibling.style.display==='none'?'▸':'▾'">
        <h3><span class="toggle-icon" style="margin-right:8px;font-size:0.8em">▾</span>${icon} ${title} <span style="color:var(--text-dim);font-size:0.7em;font-weight:normal">(${items.length})</span></h3>
      </div>
      <div style="padding:0 20px 16px">
        <table style="width:100%"><thead><tr><th>角色</th><th>Provider</th><th>模型</th><th>Temp</th><th>Tokens</th><th>使用技能</th><th>操作</th></tr></thead><tbody>
        ${items.map(r => routeRow(r, isDefaultGroup)).join('')}
        </tbody></table>
      </div>
    </div>`;
  }

  const container = $('#routes-groups');
  container.innerHTML =
    groupCard('基础角色', '⚙️', baseRoles, false) +
    groupCard('蒸馏角色', '🧪', distilledRoles, false) +
    groupCard('默认路由（回退配置）', '🔧', {...def, role_name:'default'}, true);
}

async function editDefaultRoute() {
  const settings = await api('/llm/settings');
  const d = settings.default;
  showModal('编辑默认路由', `
    <div class="form-group"><label>Provider</label><input id="m-prov" value="${esc(d.provider)}"></div>
    <div class="form-group"><label>模型</label><input id="m-model" value="${esc(d.model_name)}"></div>
    <div class="form-row"><div class="form-group"><label>Temp</label><input id="m-temp" type="number" step="0.1" value="${d.temperature}"></div><div class="form-group"><label>Tokens</label><input id="m-tokens" type="number" value="${d.max_tokens}"></div></div>
  `, async b => {
    await api('/llm/default', { method: 'PUT', body: JSON.stringify({
      role_name: 'default',
      provider: b.querySelector('#m-prov').value,
      model_name: b.querySelector('#m-model').value,
      temperature: parseFloat(b.querySelector('#m-temp').value),
      max_tokens: parseInt(b.querySelector('#m-tokens').value),
    })});
    toast('已更新'); loadLLMSettings();
  });
}
function showAddProviderModal() {
  showModal('添加 Provider', `<div class="form-group"><label>名称</label><input id="m-name" placeholder="openai"></div><div class="form-group"><label>Base URL</label><input id="m-url"></div><div class="form-group"><label>环境变量名</label><input id="m-env" placeholder="OPENAI_API_KEY"></div><div class="form-group"><label>API Key</label><input id="m-key" type="password"></div>`, async b => {
    const name = b.querySelector('#m-name').value.trim();
    const base_url = b.querySelector('#m-url').value.trim();
    const api_key_env = b.querySelector('#m-env').value.trim();
    if (!name || !base_url || !api_key_env) { toast('名称、Base URL、环境变量名不能为空', false); return; }
    await api('/llm/providers',{method:'POST',body:JSON.stringify({name,base_url,api_key_env,api_key:b.querySelector('#m-key').value||null})});
    toast('已添加'); loadLLMSettings();
  });
}
async function editProvider(name) {
  // Load current config
  const settings = await api('/llm/settings');
  const p = settings.providers.find(x => x.name === name);
  if (!p) return;
  showModal(`编辑 Provider: ${name}`, `
    <div class="form-group"><label>名称</label><input id="m-name" value="${esc(p.name)}" readonly style="opacity:0.6"></div>
    <div class="form-group"><label>Base URL</label><input id="m-url" value="${esc(p.base_url)}"></div>
    <div class="form-group"><label>环境变量名</label><input id="m-env" value="${esc(p.api_key_env)}"></div>
    <div class="form-group"><label>API Key (留空不修改)</label><input id="m-key" type="password" placeholder="留空则保持不变"></div>
  `, async b => {
    const base_url = b.querySelector('#m-url').value.trim();
    const api_key_env = b.querySelector('#m-env').value.trim();
    if (!base_url || !api_key_env) { toast('Base URL、环境变量名不能为空', false); return; }
    await api(`/llm/providers/${name}`, { method: 'PUT', body: JSON.stringify({
      name: name,
      base_url,
      api_key_env,
      api_key: b.querySelector('#m-key').value || null,
    })});
    toast('已更新'); loadLLMSettings();
  });
}
function showAddRouteModal() {
  showModal('添加路由', `<div class="form-group"><label>角色</label><input id="m-role"></div><div class="form-group"><label>Provider</label><input id="m-prov"></div><div class="form-group"><label>模型</label><input id="m-model"></div><div class="form-row"><div class="form-group"><label>Temp</label><input id="m-temp" type="number" step="0.1" value="0.7"></div><div class="form-group"><label>Tokens</label><input id="m-tokens" type="number" value="2048"></div></div>`, async b => {
    await api('/llm/routes',{method:'POST',body:JSON.stringify({role_name:b.querySelector('#m-role').value,provider:b.querySelector('#m-prov').value,model_name:b.querySelector('#m-model').value,temperature:parseFloat(b.querySelector('#m-temp').value),max_tokens:parseInt(b.querySelector('#m-tokens').value)})});
    toast('已添加'); loadLLMSettings();
  });
}
async function editRoute(role) {
  const settings = await api('/llm/settings');
  const r = settings.role_routing.find(x => x.role_name === role);
  if (!r) return;
  showModal(`编辑路由: ${role}`, `
    <div class="form-group"><label>角色</label><input id="m-role" value="${esc(r.role_name)}" readonly style="opacity:0.6"></div>
    <div class="form-group"><label>Provider</label><input id="m-prov" value="${esc(r.provider)}"></div>
    <div class="form-group"><label>模型</label><input id="m-model" value="${esc(r.model_name)}"></div>
    <div class="form-row"><div class="form-group"><label>Temp</label><input id="m-temp" type="number" step="0.1" value="${r.temperature}"></div><div class="form-group"><label>Tokens</label><input id="m-tokens" type="number" value="${r.max_tokens}"></div></div>
  `, async b => {
    await api(`/llm/routes/${role}`, { method: 'PUT', body: JSON.stringify({
      role_name: role,
      provider: b.querySelector('#m-prov').value,
      model_name: b.querySelector('#m-model').value,
      temperature: parseFloat(b.querySelector('#m-temp').value),
      max_tokens: parseInt(b.querySelector('#m-tokens').value),
    })});
    toast('已更新'); loadLLMSettings();
  });
}
async function deleteProvider(n) { if(!confirm(`删除 ${n}?`)) return; await api(`/llm/providers/${n}`,{method:'DELETE'}); toast('已删除'); loadLLMSettings(); }
async function deleteRoute(r) { if(!confirm(`删除 ${r}?`)) return; await api(`/llm/routes/${r}`,{method:'DELETE'}); toast('已删除'); loadLLMSettings(); }
async function testProvider(n) { try { const r = await api(`/llm/test?provider=${n}`,{method:'PUT'}); toast(r.ok?'连接成功':`失败: ${r.error||r.detail}`,r.ok); } catch(e) { toast(e.message, false); } }

// ══════════════════════════════════════════
//  TOKEN STATS
// ══════════════════════════════════════════
async function loadTokenStats() {
  try {
    const d = await api('/llm/tokens');
    const fmt = n => n >= 1000000 ? (n/1000000).toFixed(1) + 'M' : n >= 1000 ? (n/1000).toFixed(1) + 'K' : n;
    setEl('#token-total', fmt(d.total));
    setEl('#token-prompt', fmt(d.total_prompt));
    setEl('#token-completion', fmt(d.total_completion));
    setEl('#token-calls', d.call_count);

    const history = $('#token-history');
    if (history) {
      if (!d.recent_calls.length) {
        history.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:20px">暂无调用记录</p>';
      } else {
        history.innerHTML = `<table style="width:100%;font-size:0.85rem">
          <thead><tr style="color:var(--text-muted);text-align:left;border-bottom:1px solid var(--border)">
            <th style="padding:8px 4px">时间</th><th>角色</th><th>模型</th><th style="text-align:right">输入</th><th style="text-align:right">输出</th>
          </tr></thead>
          <tbody>${d.recent_calls.map(c => `<tr style="border-bottom:1px solid var(--border)">
            <td style="padding:6px 4px;color:var(--text-dim)">${c.time.split('T')[1]?.split('.')[0] || ''}</td>
            <td><span class="badge badge-info">${esc(c.role||'-')}</span></td>
            <td style="font-size:0.8rem;color:var(--text-dim)">${esc(c.model||'-')}</td>
            <td style="text-align:right">${c.prompt}</td>
            <td style="text-align:right">${c.completion}</td>
          </tr>`).join('')}</tbody></table>`;
      }
    }
  } catch (e) { toast('加载 Token 统计失败: ' + e.message, false); }
}
async function resetTokenStats() {
  if (!confirm('确认重置 Token 统计？')) return;
  await api('/llm/tokens/reset', {method: 'POST'});
  toast('已重置'); loadTokenStats();
}

// ── Relationship Graph Visualization ──
function renderRelationshipGraph() {
  const svg = document.getElementById('graph-svg');
  const emptyMsg = document.getElementById('graph-empty');
  if (!svg) return;

  const rels = cachedWorldState?.relationships || {};
  const chars = cachedWorldState?.characters || {};
  const charNames = Object.keys(chars);
  const relList = Object.values(rels).filter(r => r.status === 'active');

  if (charNames.length === 0 || relList.length === 0) {
    if (emptyMsg) emptyMsg.style.display = 'block';
    svg.innerHTML = '';
    return;
  }
  if (emptyMsg) emptyMsg.style.display = 'none';

  const rect = svg.getBoundingClientRect();
  const W = rect.width || 600;
  const H = rect.height || 400;
  const cx = W / 2, cy = H / 2;

  // Simple force-directed layout
  const nodes = charNames.map((name, i) => {
    const angle = (2 * Math.PI * i) / charNames.length;
    const r = Math.min(W, H) * 0.3;
    return {
      name,
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
      vx: 0, vy: 0,
      status: chars[name]?.status || 'alive',
    };
  });

  const nodeMap = {};
  nodes.forEach(n => nodeMap[n.name] = n);

  const edges = relList
    .filter(r => nodeMap[r.char1] && nodeMap[r.char2])
    .map(r => ({ source: nodeMap[r.char1], target: nodeMap[r.char2], type: r.relation_type }));

  // Simple iterative layout (100 iterations)
  for (let iter = 0; iter < 100; iter++) {
    // Repulsion between all nodes
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        let dx = nodes[j].x - nodes[i].x;
        let dy = nodes[j].y - nodes[i].y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        let force = 2000 / (dist * dist);
        nodes[i].vx -= (dx / dist) * force;
        nodes[i].vy -= (dy / dist) * force;
        nodes[j].vx += (dx / dist) * force;
        nodes[j].vy += (dy / dist) * force;
      }
    }
    // Attraction along edges
    for (const e of edges) {
      let dx = e.target.x - e.source.x;
      let dy = e.target.y - e.source.y;
      let dist = Math.sqrt(dx * dx + dy * dy) || 1;
      let force = (dist - 120) * 0.01;
      e.source.vx += (dx / dist) * force;
      e.source.vy += (dy / dist) * force;
      e.target.vx -= (dx / dist) * force;
      e.target.vy -= (dy / dist) * force;
    }
    // Center gravity
    for (const n of nodes) {
      n.vx += (cx - n.x) * 0.001;
      n.vy += (cy - n.y) * 0.001;
      n.vx *= 0.9; n.vy *= 0.9;
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(40, Math.min(W - 40, n.x));
      n.y = Math.max(40, Math.min(H - 40, n.y));
    }
  }

  // Render SVG
  let html = '<defs><marker id="arrow" viewBox="0 0 10 10" refX="25" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="var(--text-muted)"/></marker></defs>';

  // Edges
  for (const e of edges) {
    const mx = (e.source.x + e.target.x) / 2;
    const my = (e.source.y + e.target.y) / 2;
    html += `<line x1="${e.source.x}" y1="${e.source.y}" x2="${e.target.x}" y2="${e.target.y}" stroke="var(--border)" stroke-width="2"/>`;
    html += `<text x="${mx}" y="${my - 8}" text-anchor="middle" fill="var(--primary)" font-size="11" font-family="var(--font)">${esc(e.type)}</text>`;
  }

  // Nodes
  for (const n of nodes) {
    const color = n.status === 'alive' ? 'var(--primary)' : n.status === 'dead' ? 'var(--danger)' : 'var(--text-muted)';
    html += `<circle cx="${n.x}" cy="${n.y}" r="20" fill="${color}" opacity="0.15" stroke="${color}" stroke-width="2"/>`;
    html += `<text x="${n.x}" y="${n.y + 4}" text-anchor="middle" fill="var(--text)" font-size="12" font-weight="600" font-family="var(--font)">${esc(n.name)}</text>`;
  }

  svg.innerHTML = html;
}

// ── Foreshadowing Tracker ──
function renderForeshadowingTracker(pool) {
  const tracker = document.getElementById('foreshadowing-tracker');
  const pendingBadge = document.getElementById('fs-pending-count');
  const resolvedBadge = document.getElementById('fs-resolved-count');
  if (!tracker || !pool) return;

  const pending = pool.filter(f => f.status === 'pending');
  const resolved = pool.filter(f => f.status === 'resolved');
  if (pendingBadge) pendingBadge.textContent = `待收: ${pending.length}`;
  if (resolvedBadge) resolvedBadge.textContent = `已收: ${resolved.length}`;

  if (pool.length === 0) {
    tracker.innerHTML = '<div style="grid-column:1/-1; text-align:center; color:var(--text-muted); padding:20px;">暂无伏笔</div>';
    return;
  }

  tracker.innerHTML = pool.map((f, i) => {
    const isPending = f.status === 'pending';
    const age = isPending ? (cachedWorldState?.current_chapter || 0) - (f.planted_chapter || 0) : 0;
    const isStale = age > 10;
    const borderColor = isStale ? 'var(--danger)' : isPending ? 'var(--warning)' : 'var(--success)';
    const statusIcon = isStale ? '!' : isPending ? '...' : 'done';
    return `<div style="padding:12px; background:var(--bg); border-radius:8px; border-left:3px solid ${borderColor}; font-size:0.85rem;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
        <span style="color:${borderColor}; font-weight:600;">${statusIcon}</span>
        <span style="color:var(--text-muted); font-size:0.75rem;">ch${f.planted_chapter || '?'}</span>
      </div>
      <div style="color:var(--text); line-height:1.4;">${esc(f.detail || '')}</div>
      ${isStale ? `<div style="color:var(--danger); font-size:0.75rem; margin-top:4px;">已埋设 ${age} 章未回收</div>` : ''}
      ${isPending ? `<div style="margin-top:8px;"><button class="btn btn-outline btn-sm" onclick="updateForeshadowStatus(${i},'resolved')">标记已收</button></div>` : ''}
    </div>`;
  }).join('');
}

// ── Chapter Rewrite ──
async function rewriteChapter(chapterNum) {
  const reason = prompt('重写原因（可选，留空则自动优化）：');
  if (reason === null) return; // User cancelled

  toast('正在重写...');
  try {
    const result = await api(`/projects/${currentProject}/chapters/${chapterNum}/rewrite`, {
      method: 'POST',
      body: JSON.stringify({ reason: reason || '' }),
    });

    // Show comparison
    showRewriteComparison(chapterNum, result);
  } catch (e) {
    toast('重写失败: ' + e.message, false);
  }
}

function showRewriteComparison(chapterNum, result) {
  const card = document.getElementById('chapter-diff-card');
  const draftEl = document.getElementById('diff-draft');
  const finalEl = document.getElementById('diff-final');
  const statsEl = document.getElementById('diff-stats');
  if (!card) return;

  card.style.display = 'block';
  draftEl.textContent = result.original_text;
  finalEl.textContent = result.rewritten_text;

  const ev = result.evaluation || {};
  statsEl.innerHTML = `
    原文 ${result.original_word_count} 字 → 重写 ${result.rewritten_word_count} 字
    | 质量评分: ${ev.total_score || 0}/70
    <button class="btn btn-primary btn-sm" style="margin-left:16px" onclick="applyRewrite(${chapterNum})">应用重写</button>
    <button class="btn btn-outline btn-sm" style="margin-left:8px" onclick="closeChapterDiff()">取消</button>
  `;

  // Store rewritten text for apply
  window._pendingRewriteText = result.rewritten_text;

  card.scrollIntoView({ behavior: 'smooth' });
}

async function applyRewrite(chapterNum) {
  if (!window._pendingRewriteText) return toast('无待应用的重写', false);

  try {
    await api(`/projects/${currentProject}/chapters/${chapterNum}/apply-rewrite`, {
      method: 'POST',
      body: JSON.stringify({ text: window._pendingRewriteText }),
    });
    toast('重写已应用');
    window._pendingRewriteText = null;
    closeChapterDiff();
    loadChaptersPage();
  } catch (e) {
    toast('应用失败: ' + e.message, false);
  }
}

// ── Chapter Diff View ──
async function showChapterDiff(chapterNum) {
  const card = document.getElementById('chapter-diff-card');
  const draftEl = document.getElementById('diff-draft');
  const finalEl = document.getElementById('diff-final');
  const statsEl = document.getElementById('diff-stats');
  if (!card) return;

  try {
    const ch = await api(`/projects/${currentProject}/chapters/${chapterNum}`);
    const draft = ch.draft || '(无初稿)';
    const final_ = ch.final_text || ch.draft || '(无正文)';

    card.style.display = 'block';
    draftEl.textContent = draft;
    finalEl.textContent = final_;

    // Simple diff stats
    const draftLen = draft.length;
    const finalLen = final_.length;
    const diff = finalLen - draftLen;
    const wasRewritten = draft !== final_;
    statsEl.innerHTML = wasRewritten
      ? `初稿 ${draftLen} 字 → 终稿 ${finalLen} 字 (${diff >= 0 ? '+' : ''}${diff} 字) | 经过重写优化`
      : `章节共 ${finalLen} 字 | 初稿与终稿一致（无重写）`;

    card.scrollIntoView({ behavior: 'smooth' });
  } catch (e) {
    toast('加载章节失败: ' + e.message, false);
  }
}

function closeChapterDiff() {
  const card = document.getElementById('chapter-diff-card');
  if (card) card.style.display = 'none';
}

// ── Init ──
document.addEventListener('DOMContentLoaded', async () => {
  currentProject = localStorage.getItem('inkflow_project') || 'default';
  initNav();
  await loadProjects();
  loadGeneratePage();
  loadSkills();
  loadWorldState();
  loadLLMSettings();
});
