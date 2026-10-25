const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('app/front/The Court.dc.html', 'utf8');
const source = html.slice(html.indexOf('class Component extends DCLogic'), html.lastIndexOf('</script>'));
let nextTimer = 0;
const timers = new Map();
let exportedBlob, downloaded;
const anchor = { click() { downloaded = this.download; } };
const context = vm.createContext({
  DCLogic: class { constructor() { this.props = {}; } setState(p) { Object.assign(this.state, typeof p === 'function' ? p(this.state) : p); } },
  setTimeout(fn) { timers.set(++nextTimer, fn); return nextTimer; },
  clearTimeout(id) { timers.delete(id); },
  setInterval() { throw new Error('No scripted animation intervals should start'); },
  clearInterval() {},
  localStorage: { getItem() { return 'zh'; } },
  window: { matchMedia() { return { matches:false, addEventListener() {}, removeEventListener() {} }; } },
  Blob, URL: { createObjectURL(blob) { exportedBlob=blob; return 'blob:test'; }, revokeObjectURL() {} },
  document: { createElement() { return anchor; } },
});
const Court = vm.runInContext(source + '; Component', context);
const turn = (seq, minister, kind='opening', target=null, stance='pro') => ({seq, minister, kind, target, stance, influence:.8, text:`真实议题台词 ${seq}`});
const snapshot = (turns, round=0) => ({id:'s1', topic:'要不要读博', status:'debating', round, rounds_left:5-round,
  turns, tally:{pro:1,con:1,undecided:1}, ministers:[{id:'rabbit',stance:'pro',influence:.8}, {id:'fox',stance:'con',influence:.9}, {id:'banana',stance:'undecided',influence:.3}], mind:{}});
const flush = async () => { for(let i=0;i<12;i++) await Promise.resolve(); };
async function tick(c) { const id=c._playT; assert(timers.has(id)); const fn=timers.get(id); timers.delete(id); fn(); await flush(); }
async function main() {
  context.location={protocol:'https:',hostname:'court.example'};
  const locked=new Court();
  context.fetch=async()=>({status:401});
  await assert.rejects(()=>locked.api('/api/sessions'));
  assert.equal(locked.state.accessRequired,true,'The access form appears before a private court can be used');
  locked.setState({accessPassword:'test-only-password',phase:'offline',screen:4});
  let loginBody;
  context.fetch=async(url,request)=>{loginBody=JSON.parse(request.body);return {ok:true,status:200};};
  await locked.unlockCourt();
  assert.equal(loginBody.password,'test-only-password');
  assert.equal(locked.state.accessRequired,false);assert.equal(locked.state.accessPassword,'');
  assert.equal(locked.state.screen,3,'After unlocking, a failed opening can be safely submitted again');
  const c = new Court(); c.componentDidMount();
  assert.equal(c.state.wide,false);
  for (const lang of ['zh','en']) { c.state.lang=lang; const t=c.renderVals().t; for(const key of ['itvOrLabel','itvCustomPh','itvCustomBtn']) assert(t[key]); }
  c.state.lang='zh';
  c.setState({screen:4});
  assert.equal(c.renderVals().scr4Live,false);
  assert.equal(c.renderVals().noticeOn,true);
  c.setState({screen:3,topic:'要不要读博'});
  const openings=[turn(1,'rabbit'), turn(2,'fox','opening',null,'con'),turn(3,'banana','opening',null,'undecided')];
  let server=snapshot(openings), calls=[];
  c.api=async (path,body) => {
    calls.push([path,body]);
    if(path.endsWith('/round')) {
      const n=server.round+1, seq=server.turns.length;
      server=snapshot([...server.turns,turn(seq+1,'rabbit','rebuttal','fox'),turn(seq+2,'fox','rebuttal','rabbit','con')],n);
    }
    if(path.endsWith('/decree')) server=snapshot([...server.turns,turn(server.turns.length+1,'emperor','decree',body.kind,'undecided')],server.round);
    if(path.endsWith('/verdict')) server={...server,status:'decided',turns:[...server.turns,turn(server.turns.length+1,'emperor','verdict')]};
    return server;
  };
  await c.startCourt();
  assert.equal(c.state.feed.length,1,'Opening statements must play one at a time');
  assert.equal(c.renderVals().duelLine,openings[0].text);
  assert.equal(c.renderVals().t.verTitle1,'请下');
  assert(c.renderVals().speakingLabel.includes('要不要读博'));
  assert.equal(c.renderVals().compactCourtOn,true,'The focus view retains concise chat on narrow screens');
  assert.equal(c.renderVals().chatRows.length,1);
  assert.equal(calls.filter(x=>x[0].endsWith('/round')).length,0);
  c.togglePlayback(); assert.equal(c._playT,null); c.playNext();
  assert.equal(c.state.feed.length,1,'Pause stops playback and generation');
  c.togglePlayback(); assert.equal(c.state.feed.length,1,'Resume keeps the current line until its reading time ends');
  await tick(c); assert.equal(c.state.feed.length,2);
  await tick(c); assert.equal(c.state.feed.length,3);
  await tick(c); assert.equal(server.round,1);
  assert.equal(c.state.activeTurn.seq,4);
  assert.equal(c.state.cut.mode,'duo','Real rebuttals trigger duel cut-ins');
  assert(c.signatureCue('snake','卦象不利'));
  assert(!c.signatureCue('snake','没有角色线索的普通句子'));
  c.animateTurn(turn(99,'sheep','lobby','rabbit','con'),{stance:'pro'});
  assert.equal(c.state.cut.mode,'solo','Stance changes trigger signature animations');
  assert.equal(c.renderVals().hasResponse,true);
  assert.equal(c.renderVals().pauseOverlay,false);
  c.pausePlayback(); assert.equal(c.renderVals().pauseOverlay,true);
  c.navigate(5); assert.equal(c.state.screen,5,'The user can end discussion at any time');
  assert.equal(c.state.phase,'recess');
  c.setState({screen:4,phase:'debating'});
  c.togglePlayback();
  await c.pickItv('banana');
  assert.equal(c.state.itv,'banana','Banana animation remains available');
  assert.equal(c.state.paused,true);
  assert.equal(c.state.live.turns.at(-1).target,'banana');
  c.togglePlayback();
  for(let guard=0;c.state.phase==='debating' && guard<50;guard++) await tick(c);
  assert.equal(c.state.phase,'recess');
  assert.equal(c.renderVals().playbackDisabled,true);
  assert.equal(c.renderVals().interventionDisabled,true);
  assert.equal(server.round,5);
  assert.equal(new Set(c.state.feed.map(t=>t.seq)).size,c.state.feed.length);
  assert.equal(c.state.feed.length,server.turns.length);
  await c.rule('approve'); assert.equal(c.state.phase,'ruled'); assert.equal(c.state.screen,5);
  assert.equal(c.renderVals().settlementOn,true,'A successful verdict must trigger settlement');
  const settle=timers.get(c._settleT); settle();
  assert.equal(c.renderVals().settlementOn,false);
  assert.equal(c.renderVals().t.verTitle2,'已下');
  c.exportVerdict(); assert.equal(downloaded,'court-s1.json');
  const exported=JSON.parse(await exportedBlob.text());
  assert.equal(exported.status,'decided'); assert.equal(exported.topic,'要不要读博');
  assert.equal(exported.turns.length,server.turns.length);
  c.componentWillUnmount();

  const unlimited=new Court(); unlimited.closeStream();
  unlimited.setState({sid:'s1',phase:'debating',live:{...snapshot(openings,8),rounds_left:null},feed:openings});
  assert.equal(unlimited.hasMoreRounds(unlimited.state.live),true);
  assert.equal(unlimited.renderVals().ruleDisabled,false);
  unlimited.navigate(5); assert.equal(unlimited.state.phase,'recess');
  unlimited.closeStream();

  const failed=new Court(); failed.setState({topic:'另一个问题',lang:'zh'});
  failed.api=async()=>{throw new Error('offline');};
  await failed.startCourt();
  assert.equal(failed.state.phase,'offline'); assert.equal(failed.renderVals().scr4Live,false);
  assert(!failed.state.live); assert(failed.renderVals().noticeText.includes('朝堂暂不可用'));

  const stale=new Court(); stale.setState({topic:'旧议题'}); let resolve;
  stale.api=()=>new Promise(r=>{resolve=r;}); const request=stale.startCourt();
  stale.closeStream(); resolve(snapshot(openings)); await request;
  assert.equal(stale.state.live,null,'Old request cannot replace a new court');

  const retry=new Court(); retry.closeStream(); retry.setState({sid:'s1',live:snapshot(openings),phase:'offline',feed:openings});
  retry._queuedSeq=3;
  const recovered=snapshot([...openings,turn(4,'rabbit','rebuttal','fox')],1);
  retry.api=async(path,body)=>{ assert.equal(body,undefined,'Retry should recover an already completed round, not POST another'); return recovered; };
  retry.togglePlayback(); await flush(); assert.equal(retry.state.activeTurn.seq,4);
  retry.closeStream();
  const empty=new Court(); empty.closeStream(); empty.setState({sid:'s1',live:snapshot(openings),phase:'debating',feed:openings});
  empty._queuedSeq=3; empty.api=async()=>snapshot(openings);
  await empty.loadRound(); assert.equal(empty.state.phase,'recess','A silent round must not loop forever');
  empty.closeStream();
  const pending=new Court(); pending.closeStream();
  pending.setState({sid:'s1',live:snapshot(openings),feed:openings,activeTurn:openings[2],phase:'debating'});
  pending._queuedSeq=3;
  let finishRound;
  pending.api=async(path,body)=>body ? new Promise(r=>{finishRound=r;}) : snapshot(openings);
  const generation=pending.beginRound(); await flush(); pending.pausePlayback();
  finishRound(snapshot([...openings,turn(4,'rabbit','rebuttal','fox')],1)); await generation;
  assert.equal(pending.state.feed.length,3,'In-flight results cannot advance a paused debate');
  assert.equal(pending.state.activeTurn.seq,3);
  assert.equal(pending.renderVals().pausedClass,'mm-paused');
  assert.equal(pending._queue.length,1);
  assert.equal(pending.renderVals().actNo,'OPENING STATEMENTS','Paused progress follows played turns, not a future snapshot');
  pending.togglePlayback(); assert.equal(pending.state.activeTurn.seq,4);
  const staleCallback=timers.get(pending._playT);
  pending.pausePlayback(); pending.togglePlayback(); staleCallback();
  assert.equal(pending.state.activeTurn.seq,4,'A cancelled timer cannot skip a line after resume');
  pending._queue.push(turn(5,'fox','rebuttal','rabbit','con'));
  await pending.stepLine(); assert.equal(pending.state.paused,true);
  pending.closeStream();

  const speaker=new Court(); speaker.closeStream();
  speaker.setState({lang:'zh',sid:'s1',live:snapshot(openings),feed:openings,phase:'debating',emperorText:'请解释怎样避免遗漏',emperorKind:'question',emperorTarget:'fox'});
  speaker._queuedSeq=3;
  let finishReply, speechBody;
  const spoken=turn(4,'emperor','decree','fox','undecided'); spoken.detail={move:'question'};
  speaker.api=async(path,body)=>{
    if(path.endsWith('/decree')) {speechBody=body; return snapshot([...openings,spoken]);}
    return new Promise(r=>{finishReply=r;});
  };
  const speaking=speaker.sendEmperor(); await flush();
  assert.equal(speechBody.target,'fox'); assert.equal(speechBody.kind,'question');
  assert.equal(speaker.state.activeTurn.minister,'emperor','The cat emperor gets an immediate visible voice');
  speaker.togglePlayback(); assert.equal(speaker.state.paused,true,'Pause remains available while a reply is generating');
  const answer=turn(5,'fox','reply','emperor','con'); answer.detail={reason:'消息必须有人确认，否则可能被遗漏',source:'context-1',evidence:'团队跨时区',basis:'context',reply_to:4,move:'answer'};
  finishReply(snapshot([...openings,spoken,answer])); await speaking;
  assert.equal(speaker.state.feed.length,4,'Explicit pause wins over an arriving reply');
  speaker.togglePlayback(); assert.equal(speaker.state.activeTurn.seq,5);
  assert(speaker.renderVals().activeEvidence.includes('跨时区'));
  assert(speaker.renderVals().groupRows.some(g=>g.target.includes('猫皇')));
  speaker.closeStream();

  const wall=new Court(); wall.closeStream();
  wall.setState({screen:4,lang:'zh',sid:'s1',live:snapshot(openings),feed:openings,phase:'debating',factorText:'紧急消息容易遗漏',factorKind:'risk'});
  wall._queuedSeq=3; let factorState={id:'f1',text:'紧急消息容易遗漏',kind:'risk',active:true}; let wallServer=snapshot(openings);
  wall.api=async(path,body)=>{
    assert(path.endsWith('/factors'),'Editing factors must not silently start model generation');
    if(body.factor_id) factorState={...factorState,active:body.active};
    const event=turn(wallServer.turns.length+1,'emperor','factor');
    event.detail={move:'factor',outcome:body.factor_id ? 'cut' : 'added',factor:factorState};
    wallServer={...snapshot([...wallServer.turns,event]),factors:[factorState]}; return wallServer;
  };
  await wall.editFactor(); assert.equal(wall.renderVals().factorRows[0].state,'生效');
  assert.equal(wall.state.paused,true); assert(wall.renderVals().eventRows[0].result.includes('加入'));
  await wall.renderVals().factorRows[0].toggle();
  assert.equal(wall.renderVals().factorRows[0].state,'已切掉');
  assert(wall.renderVals().eventRows[0].result.includes('切掉'));
  wall.animateTurn(turn(7,'rabbit','floor','fox'),null); assert.equal(wall.state.showGroup,true);
  wall.renderVals().toggleGroup(); wall.animateTurn(turn(8,'fox','floor','rabbit'),null);
  assert.equal(wall.state.showGroup,false,'A user can keep the group view closed');
  const alliance=turn(9,'rabbit','lobby','banana'); alliance.detail={move:'ally',outcome:'allied',round:2,from_stance:'pro'};
  const betrayal=turn(10,'rabbit','lobby','fox','con'); betrayal.detail={move:'defect',outcome:'defected',round:4,from_stance:'pro',reply_to:9};
  wall.setState({feed:[...openings,alliance,betrayal]});
  assert.equal(wall.renderVals().allianceText,'尚无同盟');
  assert(wall.renderVals().trailRows.find(t=>t.name==='跺脚将军').path.includes('R4 反对'));
  assert(wall.renderVals().eventRows[0].result.includes('背盟转向'));
  const promise=turn(11,'rabbit','lobby','banana'); promise.detail={move:'ally',outcome:'allied',round:2,from_stance:'pro'};
  const pressure=turn(12,'fox','lobby','rabbit','con'); pressure.detail={move:'defect',outcome:'offer',round:4,source:'factor-f1',evidence:'紧急消息容易遗漏'};
  const switched=turn(13,'rabbit','lobby','fox','con'); switched.detail={move:'defect',outcome:'defected',round:4,from_stance:'pro',reply_to:12,former_allies:[['rabbit','banana']],drivers:{factors:['f1'],score:1.4}};
  wall.setState({feed:[...openings,promise,pressure,switched],activeTurn:switched,routeSeq:13});
  const focused=wall.renderVals();
  assert.equal(focused.compactCourtOn,true);
  assert.equal(focused.railOn,false,'Long logs and text timelines stay out of the focus view');
  assert(focused.chatRows.every(q=>!('reason' in q) && q.text.length<=43),'Chat only carries a concise claim until expanded');
  assert.equal(focused.graphNodes.find(n=>n.id==='rabbit').left,'85%','A minister visibly changes camps');
  assert(!focused.graphEdges.some(e=>e.dash==='0'),'The former alliance line must disappear after betrayal');
  assert(focused.graphEdges.some(e=>e.dash==='2 7'),'The broken alliance remains traceable');
  assert(focused.graphEdges.some(e=>e.className==='mm-edge-active'),'Current negotiations animate');
  assert(focused.routeSteps.some(r=>r.text==='背盟'));
  assert(focused.routeSteps.some(r=>r.text==='紧急消息容易遗漏'));
  assert(focused.routeResult.includes('背盟转向'));
  assert(focused.routeParent.includes('维斯帕'));
  assert(focused.routeEvidence.includes('紧急消息'));
  assert.equal(focused.graphNodes.find(n=>n.id==='rabbit').speaking,true,'The actual speaker owns the court speech bubble');
  wall.setState({feed:[...openings,promise,pressure],activeTurn:pressure});
  const negotiating=wall.renderVals();
  assert.notEqual(negotiating.graphNodes.find(n=>n.id==='fox').left,'85%','A played lobbying offer moves its speaker toward the recipient');
  assert.equal(negotiating.graphNodes.find(n=>n.id==='rabbit').left,'15%','An offer alone cannot change the recipient camp');
  wall.setState({feed:[...openings,promise,pressure,switched],activeTurn:switched});
  assert.equal(wall.renderVals().graphNodes.find(n=>n.id==='fox').left,'85%','After the reply, the negotiator returns to its camp');
  wall.closeRoute(); assert.equal(wall.renderVals().routeOn,false);
  focused.chatRows[0].open(); assert.equal(wall.state.paused,true); assert.equal(wall.state.routeSeq,13);
  const restore=new Court(); restore.api=async()=>snapshot([...openings,pressure,switched],4);
  await restore.resumeCourt('s1');
  assert.equal(restore.state.paused,true); assert.equal(restore.state.feed.length,5);
  assert.equal(restore.state.activeTurn.seq,13,'Restoring a court preserves its existing route history');
  restore.closeStream();
  const echo=turn(20,'parrot','opening',null,'con'); echo.detail={reason:'异步周报要保留紧急通道',source:'context-1',evidence:'团队跨时区'};
  const echoCourt=new Court(); echoCourt.closeStream();
  const echoSnapshot={...snapshot([...openings,echo]),ministers:[...snapshot(openings).ministers,{id:'parrot',stance:'con',influence:.6}]};
  echoCourt.setState({screen:4,lang:'zh',sid:'echo',live:echoSnapshot,feed:[...openings,echo],activeTurn:echo,phase:'debating'});
  const echoView=echoCourt.renderVals();
  assert(echoView.graphNodes.some(n=>n.id==='parrot'&&n.speaking),'Echo stands and speaks in the actual court');
  assert(echoView.emperorTargets.some(t=>t.value==='parrot'),'The emperor can address Echo');
  assert(echoView.groupRows.some(t=>t.name==='应声'),'Echo joins the group chat');
  echoCourt.animateTurn(echo,{stance:'pro'}); assert.equal(echoCourt.state.cut.id,'parrot');
  echoCourt.closeStream();
  wall.closeStream();
  console.log('frontend OK: ordered opening/rebuttal playback, event animations, pause, decree, narrow transcript, verdict, offline, stale requests, retry recovery');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
