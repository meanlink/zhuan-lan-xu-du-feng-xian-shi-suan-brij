import {identities} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,fmt,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';

const reasonOptions=['读者换号','前台把同一人显示为两人','误归并纠正','号码停用/转交','其他运营更正'];

function operationKey(prefix,payload){
  // Opaque retry token: resubmitting the same form replays the same ledger entry.
  return prefix+'-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,10)+'-'+btoa(unescape(encodeURIComponent(payload))).slice(0,20);
}

function operationNumbers(o){
  const numbers=o.numbers||[];
  if(numbers.length<=6)return esc(numbers.join('、'));
  return esc(numbers.slice(0,6).join('、'))+' 等 '+numbers.length+' 个号码';
}

function groupRow(group){  const members=group.members||[];
  return '<article class="identity-group '+(group.merged?'merged':'')+'"><div class="identity-head"><div><strong>'+esc(group.code)+'</strong>'+
    (group.merged?'<span class="tag">多号码</span>':'<span class="tag quiet">单人</span>')+
    (group.empty?'<span class="tag quiet">空身份</span>':'')+
    '<p>'+members.length+' 个号码 · 自 v'+group.created_version+' 起 · '+esc(group.note||'—')+'</p></div></div>'+
    (members.length?'<ul class="number-list">'+members.map(m=>'<li><button class="number-link" data-number="'+esc(m.number)+'"><strong>'+esc(m.number)+'</strong><small>归属自 v'+m.since_version+'</small></button></li>').join('')+'</ul>':'<p class="empty quiet">该身份当前没有号码。</p>')+
    (group.merged&&members.length?'<p class="hint">同人号码只进入训练或验证一侧；需要拆开时选择其中一个号码。</p>':'')+
    '</article>';
}

export async function identitiesPage(){
  const [ledger,operations,conflicts,basis] = await Promise.all([
    identities.ledger(),identities.operations(),identities.conflicts(),identities.jobs(),
  ]);
  workspace.identityLedger=ledger;
  const merged=ledger.groups.filter(g=>g.merged);
  const shown=merged.concat(ledger.groups.filter(g=>!g.merged&&!g.empty).slice(0,6));
  const canWrite=session.user.role!=='viewer';
  const conflictRows=conflicts.map(c=>({at:date(c.at),actor:c.actor,kind:c.action.replace('identity.','').replace('.rejected',''),
    reason:(c.detail&&(c.detail.reason||c.detail.message))||'版本过期'}));
  return heading('06 / IDENTITY LEDGER','身份归并台账',
    '把同一读者的多个登录号码合为一人，也能把误归并的号码拆回独立身份。每次修改产生一个完整版本，历史成员关系全部保留。',
    '<span class="version-chip">当前身份版本 v'+ledger.version+'</span>')+
    '<section class="identity-summary">'+
      '<div><span>身份版本</span><strong>v'+esc(ledger.version)+'</strong></div>'+
      '<div><span>号码</span><strong>'+esc(fmt(ledger.numbers))+'</strong></div>'+
      '<div><span>真实读者</span><strong>'+esc(fmt(ledger.people))+'</strong></div>'+
      '<div><span>多号码身份</span><strong>'+esc(fmt(ledger.merged_groups))+'</strong></div>'+
    '</section>'+
    '<div class="identity-grid">'+
      '<section class="panel identity-panel"><div class="section-title"><h2>归并号码为一人</h2><span>需 v'+ledger.version+' 作为前提</span></div>'+
        '<form id="merge-form"><label>号码（至少两个，用逗号或换行分隔）<textarea name="numbers" rows="3" required placeholder="RD-0007, RD-0102" '+(canWrite?'':'disabled')+'></textarea></label>'+
        '<label>归并原因<select name="reason">'+reasonOptions.map(r=>'<option>'+esc(r)+'</option>').join('')+'</select></label>'+
        '<label>补充说明（可选）<input name="note" maxlength="200" placeholder="谁在什么时间确认这是同一人"></label>'+
        '<input type="hidden" name="expected_version" value="'+ledger.version+'">'+
        '<button type="submit" class="primary" '+(canWrite?'':'disabled')+'>以 v'+ledger.version+' 为前提归并</button>'+
        '<p class="hint">账号版本过期时整笔拒绝，不会留下部分改动。同一操作号重试不会重复记账。</p></form></section>'+
      '<section class="panel identity-panel"><div class="section-title"><h2>拆分号码为独立身份</h2><span>纠正误归并</span></div>'+
        '<form id="split-form"><label>要拆出的号码<input name="number" required maxlength="120" placeholder="RD-0102" '+(canWrite?'':'disabled')+'></label>'+
        '<label>拆分原因<select name="reason">'+reasonOptions.map(r=>'<option>'+esc(r)+'</option>').join('')+'</select></label>'+
        '<label>补充说明（可选）<input name="note" maxlength="200" placeholder="例如：核实为两位不同读者"></label>'+
        '<input type="hidden" name="expected_version" value="'+ledger.version+'">'+
        '<button type="submit" class="primary" '+(canWrite?'':'disabled')+'>以 v'+ledger.version+' 为前提拆分</button>'+
        '<p class="hint">拆分只移动指定号码，其余成员关系与历史记录保持不变。</p></form></section>'+
    '</div>'+
    '<section class="panel"><div class="section-title"><h2>当前身份与号码归属</h2><span>多号码身份优先展示，另列前 6 个独立身份</span></div>'+
      (merged.length?'<p class="hint">下列 '+merged.length+' 个身份包含多个号码。点击号码可追查历史。</p>':'<p class="hint">当前没有多号码身份。可在左侧表单归并。</p>')+
      '<div class="identity-groups">'+shown.map(groupRow).join('')+'</div></section>'+
    '<div class="two-columns identity-columns">'+
      '<section class="panel"><div class="section-title"><h2>归并 / 拆分操作记录</h2><span>最近 '+operations.length+' 笔</span></div>'+
        (operations.length?'<div class="table-wrap"><table><thead><tr><th>版本</th><th>动作</th><th>号码</th><th>操作者</th><th>原因</th><th>时间</th></tr></thead><tbody>'+
          operations.map(o=>'<tr><td>v'+esc(o.version)+'<small>（基于 v'+esc(o.expected_version??'—')+'）</small></td><td>'+esc(o.kind==='merge'?'归并':o.kind==='split'?'拆分':'登记')+'</td><td>'+operationNumbers(o)+'</td><td>'+esc(o.actor)+'</td><td>'+esc(o.reason||'—')+'</td><td>'+esc(date(o.created_at))+'</td></tr>').join('')+
        '</tbody></table></div>':'<p class="empty">尚无声明的身份修改。</p>')+
        '<p class="hint">每笔记录带版本与指纹，是试验身份依据的追溯起点。</p></section>'+
      '<section class="panel"><div class="section-title"><h2>拒绝与冲突原因</h2><span>过期整笔拒绝，不产生部分改动</span></div>'+
        (conflictRows.length?table([{key:'at',label:'时间'},{key:'actor',label:'操作者'},{key:'kind',label:'动作'},{key:'reason',label:'原因'}],conflictRows):'<p class="empty">暂无冲突记录。</p>')+'</section>'+
    '</div>'+
    '<section class="panel"><div class="section-title"><h2>试验采用的身份依据</h2><span>创建时冻结，之后归并/拆分不影响排队与恢复中的试验</span></div>'+
      (basis.length?'<div class="table-wrap"><table><thead><tr><th>试验</th><th>状态</th><th>身份版本</th><th>身份指纹</th><th>多号码身份</th><th>创建时间</th></tr></thead><tbody>'+
        basis.map(j=>'<tr><td>'+esc(j.name)+'</td><td>'+esc(j.status)+(j.approved?' · 已批准':'')+'</td><td>v'+esc(j.identity_version)+(j.has_snapshot?'':'<small>（旧任务未冻结）</small>')+'</td><td><small>'+esc((j.identity_fingerprint||'—').slice(0,16))+'…</small></td><td>'+esc(j.merged_groups)+'</td><td>'+esc(date(j.created_at))+'</td></tr>').join('')+
        '</tbody></table></div>':'<p class="empty">尚无试验记录。</p>')+
      '<p class="hint">页面结果复核会显示每次试验冻结的身份版本；新试验提交时携带当时看到的版本，相撞则整笔拒绝。</p></section>'+
    '<div id="identity-detail" class="panel detail-drawer"></div>';
}

export function bindIdentities(refresh){
  const openNumber=async number=>{
    try{
      const detail=await identities.number(number);
      const host=document.querySelector('#identity-detail');
      host.innerHTML='<div class="section-title"><h2>号码 '+esc(detail.number)+' 的历史</h2><span>当前身份 '+esc(detail.current_group.code)+'</span></div>'+
        '<div class="two-columns"><div><p class="hint">当前同属一人：'+detail.current_group.numbers.map(esc).join('、')+'</p>'+
        '<div class="table-wrap"><table><thead><tr><th>身份</th><th>生效版本</th><th>结束版本</th><th>动作</th><th>操作者</th><th>原因</th></tr></thead><tbody>'+
        detail.history.map(h=>'<tr><td>'+esc(h.group_code)+'</td><td>v'+esc(h.from_version)+'</td><td>'+(h.to_version!=null?'v'+esc(h.to_version):'至今')+'</td><td>'+esc(h.operation_kind)+'</td><td>'+esc(h.actor)+'</td><td>'+esc(h.reason||'—')+'</td></tr>').join('')+
        '</tbody></table></div></div><div><div class="section-title"><h3>出现该号码的样本批次</h3></div>'+
        (detail.datasets.length?'<ul class="timeline">'+detail.datasets.map(d=>'<li><strong>'+esc(d.dataset_name)+'</strong><span>'+d.rows+' 条原始样本</span></li>').join('')+'</ul>':'<p class="empty">尚无样本引用该号码。</p>')+
        '<p class="hint">原始样本不因归并或拆分而改写；历史结果保留，只是新试验采用新的身份依据。</p></div></div>';
      host.scrollIntoView({behavior:'smooth',block:'start'});
    }catch(e){notify(e.message,true);}
  };
  document.querySelectorAll('[data-number]').forEach(b=>b.onclick=()=>openNumber(b.dataset.number));
  const mergeForm=document.querySelector('#merge-form');
  if(mergeForm&&session.user.role!=='viewer')submit(mergeForm,async f=>{
    const numbers=String(f.get('numbers')||'').split(/[\s,，、]+/).map(v=>v.trim()).filter(Boolean);
    const note=String(f.get('note')||'').trim();
    const reason=[f.get('reason'),note].filter(Boolean).join(' · ');
    const key=operationKey('merge',numbers.join('|')+reason);
    const r=await identities.merge({numbers,reason,expected_version:Number(f.get('expected_version')),operation_key:key});
    notify(r.replayed?'该操作已记账，返回原版本 v'+r.version:'已归并为一人，身份版本 v'+r.version);
    await refresh();
  });
  const splitForm=document.querySelector('#split-form');
  if(splitForm&&session.user.role!=='viewer')submit(splitForm,async f=>{
    const number=String(f.get('number')||'').trim();
    const note=String(f.get('note')||'').trim();
    const reason=[f.get('reason'),note].filter(Boolean).join(' · ');
    const key=operationKey('split',number+reason);
    const r=await identities.split({number,reason,expected_version:Number(f.get('expected_version')),operation_key:key});
    notify(r.replayed?'该操作已记账，返回原版本 v'+r.version:'号码已拆为独立身份，身份版本 v'+r.version);
    await refresh();
  });
}
