const $=id=>document.getElementById(id),v=$('video'),c=$('source'),ctx=c.getContext('2d'),pc=$('preview').getContext('2d');
let id=null,still=null,sourceW=0,sourceH=0,sourceDuration=0,mode='cam',layout='stack',style='gta',drag=null,highlights=[],words=null,wordRange='',pendingImport=null,importToken=0,selectedTime=0;
let rectEdited=false,layoutClicked=false,layoutSpecs={},editingClip=null,layoutLoadSerial=0,savedRange=null;
let rect={cam:{x:0,y:0,w:.25,h:.3},game:{x:.25,y:0,w:.75,h:1}};

// Step wizard
let currentStep=1;
const STEP_COMPLETE={1:false,2:false,3:false,4:false,5:false};
function updateStepUI(step){
  currentStep=step;
  document.querySelectorAll('[data-step]').forEach(el=>{
    const s=Number(el.dataset.step);
    if(s<step){el.classList.add('complete');el.classList.remove('active');}
    else if(s===step){el.classList.add('active');el.classList.remove('complete');}
    else{el.classList.remove('active','complete');}
  });
  document.querySelectorAll('.step-line').forEach(el=>{
    const s=Number(el.dataset.step);
    if(s<step)el.classList.add('complete');
    else el.classList.remove('complete');
  });
  document.querySelectorAll('.panel[data-step]').forEach(panel=>{
    const s=Number(panel.dataset.step);
    if(s<=step)panel.classList.remove('hidden-step');
    else panel.classList.add('hidden-step');
  });
}
function completeStep(step){
  if(step>=1&&step<=5){
    STEP_COMPLETE[step]=true;
    updateStepUI(Math.max(currentStep,step+1));
  }
}
function canProceed(step){
  switch(step){
    case 1:return !!id;
    case 2:return layoutClicked||rectEdited;
    case 3:return rectEdited&&id;
    case 4:return $('captions').checked||words?.length>0;
    case 5:return true;
  }
}
// Initialize step UI
updateStepUI(1);
// Step navigation buttons
document.querySelectorAll('[data-step-next]').forEach(btn=>{
  btn.onclick=()=>{const next=Number(btn.dataset.stepNext);if(canProceed(currentStep)){completeStep(currentStep);updateStepUI(next);}else{status('Complete the current step first.');}};
});
document.querySelectorAll('[data-step-prev]').forEach(btn=>{
  btn.onclick=()=>updateStepUI(Number(btn.dataset.stepPrev));
});
// Captions checkbox - complete step 4 when enabled
$('captions')?.addEventListener('change',()=>{if($('captions').checked)completeStep(4);});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const status=t=>$('status').textContent=t;
async function request(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(data.detail||'Request failed');return data;}
function signature(){return [id,Number($('start').value),Number($('end').value),$('language').value].join(':');}
function clearWords(){words=null;wordRange='';$('words').replaceChildren();}
function setRange(start,end){$('start').value=start;$('end').value=end;clearWords();}
function setSource(j,seek=0){editingClip=null;$('saved-edit').hidden=true;id=j.id;sourceW=j.w;sourceH=j.h;sourceDuration=j.duration;still=null;v.onloadeddata=()=>{if(seek>0&&seek<v.duration)v.currentTime=seek;};v.src='/media/'+id;c.width=j.w;c.height=j.h;$('empty-source').hidden=true;$('source-mode').textContent='SOURCE READY';completeStep(1);}
async function requireSource(){if(pendingImport&&!id){status('Source is downloading. Your layout is saved; this step will continue when ready.');await pendingImport;}if(!id)throw Error('Add a video link or upload a file first.');}
function showFrame(frame,meta,button){const image=new Image();image.onload=()=>{still=image;sourceW=image.naturalWidth;sourceH=image.naturalHeight;c.width=sourceW;c.height=sourceH;sourceDuration=meta.duration;selectedTime=frame.time;$('empty-source').hidden=true;$('source-mode').textContent=frame.kind.includes('storyboard')?'EARLY FRAME · LOW RES':'PREVIEW FRAME';v.pause();document.querySelectorAll('.frame-btn').forEach(b=>b.classList.remove('active'));button.classList.add('active');};image.src=frame.url;}
function addFrames(frames,meta){const current=$('frames').children.length;frames.slice(current).forEach((frame,index)=>{const button=document.createElement('button');button.className='frame-btn';const image=document.createElement('img');image.src=frame.url;image.alt='Source frame at '+frame.time+' seconds';const label=document.createElement('small');label.textContent=frame.time+'s';button.append(image,label);button.onclick=()=>showFrame(frame,meta,button);$('frames').append(button);if(current===0&&index===0&&!id){showFrame(frame,meta,button);if(Number($('end').value)>meta.duration)$('end').value=meta.duration;}});}
const hms=t=>{const p=String(t).trim().split(':').map(Number);if(!p.length||p.length>3||p.some(x=>!isFinite(x)||x<0))return NaN;return p.reduce((a,x)=>a*60+x,0);};
const fmt=s=>{s=Math.round(s);return Math.floor(s/3600)+':'+String(Math.floor(s%3600/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0');};
$('range-go').onclick=()=>{const a=hms($('range-start').value),b=hms($('range-end').value);if(!(b>a)){$('range-text').textContent='End must be later than start (use h:mm:ss).';return;}$('link').onclick(null,{start:a,end:b});};
$('link').onclick=async(_e,range)=>{
 const url=$('url').value.trim();if(!url){status('Paste a video link first.');return;}$('range-pick').hidden=true;
 const token=++importToken;id=null;still=null;clearWords();$('frames').replaceChildren();$('link').disabled=true;$('progress-wrap').hidden=false;$('progress').style.width='2%';$('link-status').textContent='Getting early source frames…';
 const operation=(async()=>{const {job}=await request('/link',{url,source_height:Number(($('srcq')||{}).value)||1080,...(range||{})});let completed=false;
  for(;;){const s=await request('/status/'+job);if(token!==importToken)return;if(s.preview_frames)addFrames(s.preview_frames,s.preview_meta);
   $('link-status').textContent=s.status==='done'?'Source ready. Your selected areas are preserved.':(s.message||s.stage||'Importing source');$('progress').style.width=(s.status==='done'?100:Math.min(95,(s.progress||.05)*300))+'%';
   if(s.status==='error')throw Error(s.error);
   if(s.status==='needs_range'){$('range-pick').hidden=false;$('range-title').textContent='This video is '+fmt(s.duration_total)+' long';$('range-text').textContent='Downloading all of it would be huge. Choose the part you need (up to '+fmt(s.max_range)+'); only that part is downloaded. Preview frames above still show the whole video.';$('range-end').value=fmt(Math.min(s.duration_total,1800));$('link-status').textContent='Pick the part of this long video to import.';status('Long video: pick the part to import.');$('progress-wrap').hidden=true;return;}
   if(s.status==='done'&&!completed){completed=true;setSource(s,selectedTime);if(!Number($('end').value)||Number($('end').value)>s.duration)$('end').value=Math.min(30,s.duration);$('link-status').textContent='Source ready. Your selected areas are preserved.';status('Source ready. Find highlights or export your selected range.');}
   if(completed&&(s.preview_status!=='loading'||s.preview_frames?.length>=4))break;
   await sleep(700);
  }
 })();pendingImport=operation;
 try{await operation;}catch(e){$('link-status').textContent=e.message;status(e.message);}finally{if(token===importToken){pendingImport=null;$('link').disabled=false;}}
 if(token===importToken&&id&&$('auto-analyze').checked&&!$('analyze').disabled)await $('analyze').onclick();
};
$('file').onchange=async()=>{try{if(!$('file').files[0])return;++importToken;pendingImport=null;id=null;still=null;$('link').disabled=false;$('frames').replaceChildren();status('Uploading source…');const form=new FormData();form.append('file',$('file').files[0]);const response=await fetch('/upload',{method:'POST',body:form});const j=await response.json();if(!response.ok)throw Error(j.detail);$('url').value='';setSource(j);setRange(0,Math.min(30,j.duration));$('link-status').textContent='File ready';status('Draw the facecam and gameplay areas.');}catch(e){status(e.message);}};
function showHighlights(jobs){highlights=jobs.flatMap(job=>(job.clips||[]).map(clip=>({...clip,job:job.job||job.id,video:job.title})));highlights=highlights.filter(h=>Number.isFinite(h.start)&&Number.isFinite(h.end));const select=$('recent');select.replaceChildren();if(!highlights.length){const option=document.createElement('option');option.textContent='No highlights yet — add a video and Find highlights';select.append(option);}highlights.forEach((h,index)=>{const option=document.createElement('option');option.value=index;option.textContent=h.start.toFixed(1)+'–'+h.end.toFixed(1)+'s · '+h.title+(h.score!==undefined?' · activity '+h.score:'');select.append(option);});}
async function openHighlight(){const h=highlights[Number($('recent').value)];if(!h)return;const j=await request('/highlight-source',{job:h.job});setSource(j,h.start);setRange(h.start,h.end);status('Moment loaded. Review the source and selected areas.');}
$('import').onclick=()=>openHighlight().catch(e=>status(e.message));
$('analyze').onclick=async()=>{const button=$('analyze');button.disabled=true;try{if(!id&&!pendingImport&&$('url').value.trim()){await $('link').onclick();}await requireSource();status('Finding activity highlights locally…');const {job}=await request('/analyze',{id,url:undefined,source_height:Number(($('srcq')||{}).value)||1080,count:Number($('count').value),length:Number($('length').value),min_len:Number($('minlen').value)});for(;;){const s=await request('/analysis/'+job);status((s.stage||s.status)+' · '+Math.round((s.progress||0)*100)+'%');if(s.status==='error')throw Error(s.error);if(s.status==='done'){showHighlights([s]);await openHighlight();status('Highlights ready. Choose a moment, review it and export.');break;}await sleep(900);}}catch(e){status(e.message);}finally{button.disabled=false;}};
['cam','game'].forEach(k=>$(k).onclick=()=>{mode=k;['cam','game'].forEach(x=>$(x).classList.toggle('active',x===k));});
function point(e){const b=c.getBoundingClientRect();return{x:Math.max(0,Math.min(1,(e.clientX-b.left)/b.width)),y:Math.max(0,Math.min(1,(e.clientY-b.top)/b.height))};}
c.onpointerdown=e=>{if(!still&&v.readyState<2)return;drag=point(e);c.setPointerCapture(e.pointerId);};c.onpointermove=e=>{if(!drag)return;rectEdited=true;const p=point(e);rect[mode]={x:Math.min(p.x,drag.x),y:Math.min(p.y,drag.y),w:Math.max(.01,Math.abs(p.x-drag.x)),h:Math.max(.01,Math.abs(p.y-drag.y))};if(rectEdited&&id)completeStep(3);};c.onpointerup=()=>drag=null;c.onpointercancel=()=>drag=null;
$('save').onclick=()=>{localStorage.setItem('ajay-crop',JSON.stringify({rect,top:$('top').value,layout}));status('Layout saved in this browser.');};$('load').onclick=()=>{try{const j=JSON.parse(localStorage.getItem('ajay-crop')||'null');if(j){rect=j.rect;rectEdited=true;$('top').value=j.top;setLayout(j.layout||'stack');status('Saved layout loaded.');}else status('No saved layout yet.');}catch(e){status('Saved layout could not be read.');}};
function setLayout(value){layout=value;if($('edit-top'))$('edit-top').value=$('top').value;document.querySelectorAll('[data-layout]').forEach(b=>b.classList.toggle('active',b.dataset.layout===layout));$('height-control').hidden=['blur','fill','game'].includes(layout);}
document.querySelectorAll('[data-layout]').forEach(b=>b.onclick=()=>{layoutClicked=true;setLayout(b.dataset.layout);completeStep(2);});document.querySelectorAll('[data-style]').forEach(b=>b.onclick=()=>{style=b.dataset.style;document.querySelectorAll('[data-style]').forEach(x=>x.classList.toggle('active',x===b));});
v.onplay=()=>still=null;v.ontimeupdate=()=>{const end=Number($('end').value);if(end>Number($('start').value)&&v.currentTime>end&&end<v.duration)v.pause();};
['start','end','language'].forEach(key=>$(key).addEventListener('change',()=>{clearWords();if(key==='start'&&id)v.currentTime=Math.max(0,Math.min(v.duration||Infinity,Number($('start').value)));}));
function cover(source,r,x,y,w,h){const sw=r.w*sourceW,sh=r.h*sourceH,ratio=Math.max(w/sw,h/sh),cw=w/ratio,ch=h/ratio;pc.drawImage(source,r.x*sourceW+(sw-cw)/2,r.y*sourceH+(sh-ch)/2,cw,ch,x,y,w,h);}
function captionPreview(){if(!$('captions').checked)return;let line='YOUR NEXT BIG MOMENT';if(words&&wordRange===signature()&&words.length){const time=Math.max(0,v.currentTime-Number($('start').value));let index=words.findIndex(w=>time>=w.start&&time<=w.end);if(index<0)index=0;line=words.slice(Math.floor(index/3)*3,Math.floor(index/3)*3+3).map(w=>w.text).join(' ');}const spec=layoutSpecs[layout];if(!spec)return;const scale=pc.canvas.width/spec.width,fs=(style==='clean'?58:72)*Math.min(spec.width/1080,spec.height/1920)*scale;pc.save();pc.textAlign='center';pc.textBaseline='middle';pc.font='900 '+fs+'px Arial';const max=pc.canvas.width*.9;while(pc.measureText(line).width>max){const size=parseFloat(pc.font.match(/(\d+(?:\.\d+)?)px/)[1]);pc.font='900 '+Math.max(8,size-1)+'px Arial';if(size<=8)break;}const position=Number($('caption-y').value)===1450?spec.caption_y:Number($('caption-y').value)/1920*spec.height;pc.lineWidth=3;pc.strokeStyle='#160b22';pc.shadowBlur=style==='gta'?8:0;pc.shadowColor='#ff4ba5';pc.strokeText(line,pc.canvas.width/2,position*scale);pc.fillStyle=style==='gta'?'#58e8f7':style==='bold'?'#d4fb58':'white';pc.fillText(line,pc.canvas.width/2,position*scale);pc.restore();}
function hookPreview(){const text=$('hook').value.trim();if(!text||($('hook-enabled')&&!$('hook-enabled').checked))return;const spec=layoutSpecs[layout];if(!spec)return;const duration=Number($('hook-duration')?.value||8);if(!still&&v.currentTime-Number($('start').value)>duration)return;const factor=pc.canvas.width/spec.width,scale=Math.min(spec.width/1080,spec.height/1920);let raw=text.slice(0,60).toUpperCase(),lines=[],line='';const width=Math.max(12,Math.floor(spec.width/(82*scale*.6)));for(const word of raw.split(/\s+/)){if(line&&(line+' '+word).length>width){lines.push(line);line=word;}else line+=(line?' ':'')+word;}if(line)lines.push(line);lines=lines.slice(0,3);const size=Math.round((lines.length===1?78:lines.length===2?72:66)*scale)*factor,pad=Math.max(8,Math.round(26*scale))*factor,lh=Math.round(size*1.22);pc.save();pc.font='900 '+size+'px Arial';pc.textAlign='center';pc.textBaseline='top';const boxW=Math.min(pc.canvas.width*.94,Math.max(...lines.map(t=>pc.measureText(t).width))+pad*2),boxH=lh*lines.length+pad*2,y=Math.max(pad,Math.min(spec.hook_y*factor,pc.canvas.height-boxH-pad));if($('hook-background')?.checked!==false){pc.fillStyle='rgba(0,0,0,.88)';pc.fillRect((pc.canvas.width-boxW)/2,y,boxW,boxH);}pc.fillStyle='white';pc.strokeStyle='black';pc.lineWidth=2*factor;lines.forEach((value,i)=>{pc.strokeText(value,pc.canvas.width/2,y+pad+i*lh);pc.fillText(value,pc.canvas.width/2,y+pad+i*lh);});pc.restore();}
function paint(){const source=still||(v.readyState>=2?v:null);if(source){if(!still){sourceW=v.videoWidth;sourceH=v.videoHeight;}if(sourceW&&sourceH){ctx.drawImage(source,0,0,c.width,c.height);['cam','game'].forEach(k=>{const r=rect[k];ctx.strokeStyle=k==='cam'?'#ff4ba5':'#4ade80';ctx.lineWidth=Math.max(2,c.width/350);ctx.strokeRect(r.x*c.width,r.y*c.height,r.w*c.width,r.h*c.height);});pc.clearRect(0,0,540,960);drawNativeLayout(source);captionPreview();hookPreview();}}$('height-value').textContent=$('top').value+'%';requestAnimationFrame(paint);}paint();
function collectWords(){if(words&&wordRange===signature()){const duration=Number($('end').value)-Number($('start').value);if(words.some(w=>!Number.isFinite(w.start)||!Number.isFinite(w.end)||w.start<0||w.end<=w.start||w.end>duration+.1))throw Error('Check edited subtitle start/end times before exporting.');return words;}return null;}
function renderWords(){const editor=$('words');editor.replaceChildren();const timing=$('timing-editor')?.checked;editor.classList.toggle('timing',timing);for(const word of words||[]){const input=document.createElement('input');input.value=word.text;input.title=word.start.toFixed(2)+'–'+word.end.toFixed(2)+'s';input.oninput=()=>word.text=input.value;if(!timing){editor.append(input);continue;}const row=document.createElement('div');row.className='word-timing';row.append(input);for(const key of ['start','end']){const field=document.createElement('input');field.type='number';field.step='.01';field.min='0';field.value=Math.round(word[key]*1000)/1000;field.setAttribute('aria-label',key+' '+word.text);field.onchange=()=>{word[key]=Number(field.value);field.setAttribute('aria-invalid',String(!Number.isFinite(word[key])||word.start<0||word.end<=word.start));};row.append(field);}const merge=document.createElement('button');merge.textContent='Merge next';const index=words.indexOf(word);merge.disabled=index===words.length-1;merge.onclick=()=>{const next=words[index+1];words.splice(index,2,{start:Math.min(word.start,next.start),end:Math.max(word.end,next.end),text:word.text+' '+next.text});renderWords();};const split=document.createElement('button');split.textContent='Split words';split.onclick=()=>{const tokens=word.text.trim().split(/\s+/);if(tokens.length<2){status('Type two or more words in this row to split it.');return;}const total=tokens.reduce((n,t)=>n+t.length+1,0);let time=word.start;const parts=tokens.map(t=>{const start=time;time+=(word.end-word.start)*(t.length+1)/total;return{start,end:time,text:t};});words.splice(index,1,...parts);renderWords();status('Words split with estimated within-cue timings; review them before applying.');};row.append(merge,split);editor.append(row);}}
async function generateSubtitles(){await requireSource();status('Starting local subtitles…');const range=signature();const {job}=await request('/transcribe',{id,start:Number($('start').value),end:Number($('end').value),language:$('language').value});for(;;){const s=await request('/status/'+job);status(s.message||s.status);if(s.status==='error')throw Error(s.error);if(s.status==='done'){if(signature()!==range)throw Error('Selected range changed. Generate subtitles for the current range.');words=s.words;wordRange=range;renderWords();const text=words.map(w=>w.text).join(' ');if(!$('clip-title').value)$('clip-title').value=text.split(/\s+/).slice(0,9).join(' ');if(!$('post-caption').value)$('post-caption').value=text.slice(0,220)+(text.length>220?'…':'')+'\n\n#Gaming #Clips';status(words.length?'Subtitles ready. Edit any word before exporting.':'No speech detected in this range.');completeStep(4);return;}await sleep(1100);}}
$('transcribe').onclick=async()=>{$('transcribe').disabled=true;try{await generateSubtitles();}catch(e){status(e.message);}finally{$('transcribe').disabled=false;}};
function exportSettings(source,start,end){const b={id:source,...rect,layout,aspect:$('aspect').value,resolution:Number($('resolution').value),fps:Number($('fps').value),top:Number($('top').value)/100,start,end,captions:$('captions').checked,caption_style:style,caption_y:Number($('caption-y').value),language:$('language').value,hook:$('hook').value,title:$('clip-title').value,post_caption:$('post-caption').value};if(window.customCamId&&$('custom-cam-enabled')?.checked)b.custom_cam=window.customCamId;if(source===id&&start===Number($('start').value)&&end===Number($('end').value)){const edited=collectWords();if(edited!==null)b.words=edited;}return b;}
async function runExport(body,prefix=''){const {job}=await request('/export',body);for(;;){const s=await request('/status/'+job);status(prefix+(s.message||'Rendering…'));if(s.status==='error')throw Error(s.error);if(s.status==='done')return s;await sleep(1000);}}
function showDownload(s){$('vtt').hidden=!s.srt;if(s.srt)$('vtt').href='/text/'+s.file+'/vtt';$('download').href='/media/'+s.file;$('download').hidden=false;$('srt').hidden=!s.srt;if(s.srt)$('srt').href=s.srt;}
$('export').onclick=async()=>{const button=$('export');button.disabled=true;$('download').hidden=true;$('srt').hidden=true;try{await requireSource();const s=await runExport(exportSettings(id,Number($('start').value),Number($('end').value)));showDownload(s);status('Ready · '+s.meta.w+' × '+s.meta.h+' · '+s.encoder+' · '+s.caption_words+' caption words');await refreshLibrary();}catch(e){status(e.message);}finally{button.disabled=false;}};
$('batch').onclick=async()=>{const button=$('batch');button.disabled=true;$('export').disabled=true;try{await requireSource();const selected=highlights[Number($('recent').value)];if(!selected)throw Error('Find highlights first.');const candidates=highlights.filter(h=>h.job===selected.job);const source=await request('/highlight-source',{job:selected.job});for(let i=0;i<candidates.length;i++){const h=candidates[i],body=exportSettings(source.id,h.start,h.end);body.title=($('clip-title').value||'Highlight')+' '+(i+1);const s=await runExport(body,'Clip '+(i+1)+' / '+candidates.length+' · ');showDownload(s);await refreshLibrary();}status(candidates.length+' clips exported. Open My clips to preview and download.');}catch(e){status(e.message);}finally{button.disabled=false;$('export').disabled=false;}};
// Library with many clips: only fetch a video's metadata once it scrolls near the screen.
const lazyObserver=('IntersectionObserver' in window)?new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){e.target.preload='metadata';e.target.load();lazyObserver.unobserve(e.target);}}),{rootMargin:'400px'}):null;
function ratingMessage(result){return 'Saved · '+result.ratings+' different moment'+(result.ratings===1?'':'s')+' · '+(result.message||(result.fitted?'Preferences updated.':'Rate at least eight different moments.'));}
function appendVisualReview(parent,review){if(!review?.frames?.length)return;const details=document.createElement('details'),title=document.createElement('summary');title.textContent='AI frame observations';details.append(title);const grid=document.createElement('div');grid.className='vision-grid';review.frames.forEach((frame,index)=>{const figure=document.createElement('figure'),image=document.createElement('img'),caption=document.createElement('figcaption');image.loading='lazy';if(/^\/vision\/frame\/[a-f0-9]{64}\/[012]$/.test(frame.image||''))image.src=frame.image;image.alt='Scene sample '+(index+1);caption.textContent=frame.description;figure.append(image,caption);grid.append(figure);});details.append(grid);parent.append(details);}
function lazyVideo(v){if(lazyObserver){v.preload='none';lazyObserver.observe(v);}else v.preload='metadata';}
const libSel=new Set();let libClips=[],ytPoll=null;
async function refreshLibrary(){const clips=await request('/library');libClips=clips;const ids=new Set(clips.map(c=>c.id));[...libSel].forEach(i=>{if(!ids.has(i))libSel.delete(i);});$('library-count').textContent=clips.length;const host=$('library');host.replaceChildren();if(!clips.length){const empty=document.createElement('div');empty.className='empty-library';empty.textContent='Your first clip belongs here. Export a moment to start your library.';host.append(empty);}for(const clip of clips){const card=document.createElement('article');card.className='clip-card';card.dataset.file=clip.id;const pick=document.createElement('input');pick.type='checkbox';pick.className='clip-select';pick.title='Select this clip';pick.checked=libSel.has(clip.id);pick.onchange=()=>{if(pick.checked)libSel.add(clip.id);else libSel.delete(clip.id);libTools();};const tag=document.createElement('div');tag.className='yt-tag';tag.textContent='○ Not uploaded';const video=document.createElement('video');video.src='/media/'+clip.id;video.controls=true;lazyVideo(video);const title=document.createElement('h3');title.textContent=clip.title;const meta=document.createElement('p');meta.textContent=(clip.meta.duration||0).toFixed(1)+' seconds · '+(clip.settings.layout||'stack')+' · '+new Date(clip.created*1000).toLocaleDateString();const links=document.createElement('div');links.className='card-links';const download=document.createElement('a');download.href='/media/'+clip.id;download.download='ninjastudio-'+clip.id+'.mp4';download.textContent='↓ MP4';links.append(download);if(clip.srt){const sub=document.createElement('a');sub.href='/text/'+clip.id+'/srt';sub.textContent='↓ SRT';links.append(sub);}const edit=document.createElement('button');edit.textContent='Edit clip';edit.onclick=()=>openSavedClip(clip.id).catch(e=>status(e.message));const del=document.createElement('button');del.type='button';del.className='clip-delete';del.textContent='🗑 Delete';del.title='Delete from this computer (not from YouTube)';del.onclick=()=>deleteClips([clip.id]);links.append(edit,del);card.append(pick,video,tag,title,meta,links);appendVisualReview(card,clip.settings.visual_review);if(clip.settings.features)liveStars(card,clip.id);host.append(card);}libTools();updateYtTags();}
// YouTube tag on every saved clip: uploaded (with link), waiting / uploading, failed, or not uploaded. Polls while uploads run.
async function updateYtTags(){clearTimeout(ytPoll);let states;try{states=await request('/youtube/clip-states');}catch(e){return;}let busy=false;
 document.querySelectorAll('#library .clip-card').forEach(card=>{const tag=card.querySelector('.yt-tag');if(!tag)return;const s=states[card.dataset.file];tag.className='yt-tag';tag.replaceChildren();tag.title='';card.dataset.uploaded=s&&s.status==='uploaded'?'1':'';
  if(!s){tag.textContent='○ Not uploaded';return;}
  if(s.status==='uploaded'){tag.classList.add('done');tag.append('✓ On YouTube'+((s.channels||[]).length?' · '+s.channels.join(', '):'')+' ');if(s.url){const a=document.createElement('a');a.href=s.url;a.target='_blank';a.rel='noopener';a.textContent='View ↗';tag.append(a);}return;}
  if(s.status==='error'){tag.classList.add('fail');tag.textContent='✕ Upload failed';tag.title=s.error||'';return;}
  busy=true;tag.classList.add('busy');tag.textContent=(s.status==='queued'?'⏳ Waiting to upload':'⏳ Uploading '+Math.round((s.progress||0)*100)+'%')+(s.channel_title?' → '+s.channel_title:'');});
 if(busy)ytPoll=setTimeout(updateYtTags,2000);}
function libTools(){const n=libSel.size;$('lib-selected').textContent=n+' selected';$('lib-upload').disabled=!n;$('lib-delete').disabled=!n;const all=$('lib-select-all');all.checked=libClips.length>0&&n===libClips.length;all.indeterminate=n>0&&n<libClips.length;}
function libSelect(pick){libSel.clear();document.querySelectorAll('#library .clip-card').forEach(card=>{const on=pick(card);if(on)libSel.add(card.dataset.file);const box=card.querySelector('.clip-select');if(box)box.checked=on;});libTools();}
async function deleteClips(ids){if(!ids.length)return;if(!confirm((ids.length===1?'This clip':ids.length+' clips')+' will be deleted from this computer. A video already uploaded to YouTube stays on YouTube. Delete?'))return;
 try{const r=await request('/clips/delete',{ids});ids.forEach(i=>libSel.delete(i));$('lib-status').textContent=r.deleted.length?'Deleted from this computer.':'Nothing was deleted.';}catch(e){$('lib-status').textContent=e.message;}
 await refreshLibrary().catch(e=>status(e.message));}
$('lib-select-all').onchange=e=>libSelect(()=>e.target.checked);
$('lib-select-new').onclick=()=>libSelect(card=>!card.dataset.uploaded);
$('lib-delete').onclick=()=>deleteClips([...libSel]);
$('lib-upload').onclick=async()=>{const items=libClips.filter(c=>libSel.has(c.id)).map(c=>({clip_id:c.id,title:c.title}));if(!items.length)return;
 const again=items.filter(i=>document.querySelector('#library .clip-card[data-file="'+i.clip_id+'"]')?.dataset.uploaded).length;
 if(again&&!confirm(again+' selected clip(s) are already on YouTube. Upload them again?'))return;
 $('lib-upload').disabled=true;$('lib-status').textContent='Starting upload of '+items.length+' clip(s)…';
 try{const r=await request('/youtube/upload-batch',{items,channel:$('lib-channel')?.value||''});const failed=r.jobs.filter(j=>j.error).length;$('lib-status').textContent=(r.jobs.length-failed)+' clip(s) queued for YouTube. They upload one by one, keep the app open.'+(failed?' '+failed+' clip(s) could not be found.':'');libSelect(()=>false);}
 catch(e){$('lib-status').textContent=/not connected/i.test(e.message)?'Connect your YouTube channel first (▶ Connect YouTube at the top).':e.message;libTools();}
 updateYtTags();};
// banner and footer shortcuts: open a view (as if its sidebar button was pressed) and scroll to the right place
const openView=v=>{const n=document.querySelector('.sidebar [data-view='+v+']');if(n&&!n.classList.contains('active'))n.click();};
document.querySelectorAll('[data-goto]').forEach(b=>b.onclick=()=>{openView(b.dataset.goto);window.scrollTo({top:0,behavior:'smooth'});});
$('hero-start').onclick=()=>{openView('editor');$('url').scrollIntoView({behavior:'smooth',block:'center'});setTimeout(()=>$('url').focus({preventScroll:true}),450);};
document.querySelectorAll('.go-live-link').forEach(b=>b.onclick=()=>{openView('editor');$('golive-panel').scrollIntoView({behavior:'smooth',block:'start'});});
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===b));$('editor-view').hidden=b.dataset.view!=='editor';$('library-view').hidden=b.dataset.view!=='library';if(b.dataset.view==='library')refreshLibrary().catch(e=>status(e.message));});$('refresh-library').onclick=()=>refreshLibrary().catch(e=>status(e.message));
request('/highlights').then(showHighlights).catch(e=>status(e.message));refreshLibrary().catch(e=>status(e.message));

$('make').onclick=async()=>{const url=$('url').value.trim();if(!url&&!id){status('Paste a video link or upload a file first.');return;}
 const b=$('make');b.disabled=true;$('make-results').hidden=false;$('make-results').querySelector('.star-ask')?.remove();$('make-grid').replaceChildren();$('make-progress').style.width='2%';
 try{const {job}=await request('/make',{...(url?{url}:{id}),count:Number($('count').value),mode:$('mode').value,source_height:Number(($('srcq')||{}).value)||1080,accurate:$('accurate').value,min_len:Number($('minlen').value),max_len:Number($('length').value),layout:makeLayout(),aspect:$('aspect').value,resolution:Number($('resolution').value),fps:Number($('fps').value),cam:rect.cam,game:rect.game,top:Number($('top').value)/100,caption_style:style,language:$('language').value==='auto'?'':$('language').value,...(window.customCamId&&$('custom-cam-enabled')?.checked?{custom_cam:window.customCamId}:{})});
  const shown=new Set();
  for(;;){const s=await request('/make/'+job);$('make-status').textContent=(s.stage||s.status)+' · '+Math.round((s.progress||0)*100)+'%';$('make-progress').style.width=Math.max(2,(s.progress||0)*100)+'%';
   (s.clips||[]).forEach(c=>{if(shown.has(c.file))return;shown.add(c.file);const d=document.createElement('div');d.className='mk';d.dataset.file=c.file;
    if(c.error){d.textContent='Failed: '+c.error.slice(0,120);}else{const vid=document.createElement('video');vid.src='/media/'+c.file;vid.controls=true;vid.preload='metadata';const t=document.createElement('b');t.textContent=c.title;const m=document.createElement('small');m.textContent=Math.round(c.start)+'–'+Math.round(c.end)+'s · score '+c.score+(c.hook?' · "'+c.hook+'"':'');const a=document.createElement('a');a.href='/media/'+c.file;a.download='ninjastudio-'+c.file+'.mp4';a.textContent='Download MP4';const rs=document.createElement('small');rs.textContent=c.reason||'';const vb=document.createElement('div');vb.className='viral';const ax=c.axes||{};const fmt=v=>v==null?'–':v;vb.title='Viral score is a heuristic: loudness, shouting, what is said, on-screen action and a local AI read. Your star ratings tune it.';vb.innerHTML='<b>🔥 Viral '+(c.viral??'–')+'</b><span>Energy '+fmt(ax.energy)+'</span><span>Action '+fmt(ax.action)+'</span><span>Words '+fmt(ax.words)+'</span><span>AI '+fmt(ax.ai)+'</span>';const stars=document.createElement('div');stars.className='stars';stars.title='Rate this clip: it teaches Ninja Studio Clipping what a good clip is';
    for(let n=1;n<=5;n++){const sb=document.createElement('button');sb.textContent='★';sb.setAttribute('aria-label','Rate '+n+' star'+(n===1?'':'s'));sb.onclick=async()=>{try{const r=await request('/feedback',{file:c.file,rating:n});[...stars.children].forEach((x,i)=>x.classList.toggle('on',i<n));fb.textContent=ratingMessage(r);}catch(e){fb.textContent=e.message;}};stars.append(sb);}
    const fb=document.createElement('small');fb.className='fb';fb.textContent='Rate this clip ↑';const edit=document.createElement('button');edit.textContent='Edit clip';edit.onclick=()=>openSavedClip(d.dataset.file).catch(e=>status(e.message));d.append(vid,t,vb,m,rs,a,edit,stars,fb);}
    appendVisualReview(d,c.visual_review);$('make-grid').append(d);});
   if(s.status==='error')throw Error(s.error);if(s.status==='done'){if(!(s.clips||[]).length){$('make-status').textContent=s.stage||'No moments matched. Broaden your filters and try again.';break;}$('make-status').textContent='Done · '+(s.clips||[]).length+' clips in '+s.elapsed_seconds+'s · also in My clips ('+(s.engine||'')+')';break;}
   await sleep(1000);}}catch(e){$('make-status').textContent=e.message;}finally{b.disabled=false;}};

const PRESETS={tl:{cam:{x:0,y:0,w:.24,h:.32},game:{x:.24,y:0,w:.76,h:1}},tr:{cam:{x:.76,y:0,w:.24,h:.32},game:{x:0,y:0,w:.76,h:1}},
 bl:{cam:{x:0,y:.68,w:.24,h:.32},game:{x:.24,y:0,w:.76,h:1}},br:{cam:{x:.76,y:.68,w:.24,h:.32},game:{x:0,y:0,w:.76,h:1}},bc:{cam:{x:.37,y:.68,w:.26,h:.32},game:{x:0,y:0,w:1,h:.68}}};
let preset=null;
function applyPreset(k,save=true){preset=k;document.querySelectorAll('[data-preset]').forEach(b=>b.classList.toggle('on',b.dataset.preset===k));
 if(k==='none'){$('preset-note').textContent='Blurred full frame, no separate facecam.';document.querySelector('[data-layout=blur]')?.click();}
 else{rectEdited=true;rect={cam:{...PRESETS[k].cam},game:{...PRESETS[k].game}};$('preset-note').textContent='Preset set. Fine-tune by drawing in step 03 if your cam sits a bit differently.';document.querySelector('[data-layout=stack]')?.click();}
 if(save)try{localStorage.setItem('neonclipping-preset',k);}catch(e){}}
document.querySelectorAll('[data-preset]').forEach(b=>b.onclick=()=>applyPreset(b.dataset.preset));
try{const k=localStorage.getItem('neonclipping-preset');if(k)applyPreset(k,false);}catch(e){}

// Make clips uses what the user set up: preset or drawn boxes -> that layout; else the layout they clicked; else blurred full frame.
function makeLayout(){return (layoutClicked||rectEdited)?layout:'blur';}

async function loadNativeLayouts(){
 const serial=++layoutLoadSerial;const entries=await request('/layouts?top='+Number($('top').value)/100+'&aspect='+$('aspect').value+'&resolution='+$('resolution').value);if(serial!==layoutLoadSerial)return;pc.canvas.width=540;pc.canvas.height=Math.round(540*entries[0].height/entries[0].width);
 layoutSpecs=Object.fromEntries(entries.map(x=>[x.id,x]));
 for(const host of [$('layouts'),$('edit-layouts')].filter(Boolean)){host.replaceChildren();
 for(const entry of entries){const button=document.createElement('button');button.className='choice';button.dataset.layout=entry.id;
 const icon=document.createElement('span');icon.className='mini native-layout-mini';icon.style.width=(52*entry.width/entry.height)+'px';icon.setAttribute('aria-hidden','true');
 if(entry.mode==='blur'){const backdrop=document.createElement('i');backdrop.className='layout-backdrop';const inset=document.createElement('i');inset.className='layout-inset';icon.append(backdrop,inset);}
 else for(const layer of entry.layers){const shape=document.createElement('i');shape.className='layout-'+layer.source+(layer.circle?' layout-circle':'');Object.assign(shape.style,{left:(layer.x/entry.width*100)+'%',top:(layer.y/entry.height*100)+'%',width:(layer.w/entry.width*100)+'%',height:(layer.h/entry.height*100)+'%'});icon.append(shape);}
 const name=document.createElement('b');name.textContent=entry.name;const desc=document.createElement('small');desc.textContent=entry.description;
 button.append(icon,name,desc);button.onclick=()=>{layoutClicked=true;setLayout(entry.id);};host.append(button);}}
 setLayout(layout);
}
function drawNativeLayout(source){
 const spec=layoutSpecs[layout];if(!spec)return;const pw=pc.canvas.width,ph=pc.canvas.height,sx=pw/spec.width,sy=ph/spec.height;
 if(spec.mode==='blur'){pc.save();pc.filter='blur(16px)';cover(source,{x:0,y:0,w:1,h:1},-15,-15,pw+30,ph+30);pc.restore();const ratio=Math.min(pw/sourceW,ph/sourceH),w=sourceW*ratio,h=sourceH*ratio;pc.drawImage(source,0,0,sourceW,sourceH,(pw-w)/2,(ph-h)/2,w,h);}
 else{pc.fillStyle='#000';pc.fillRect(0,0,pw,ph);for(const layer of spec.layers){pc.save();if(layer.circle){pc.beginPath();pc.arc((layer.x+layer.w/2)*sx,(layer.y+layer.h/2)*sy,Math.min(layer.w*sx,layer.h*sy)/2,0,Math.PI*2);pc.clip();}pc.filter=layer.source==='cam'?camFilter():'none';cover(source,layer.source==='full'?{x:0,y:0,w:1,h:1}:rect[layer.source],layer.x*sx,layer.y*sy,layer.w*sx,layer.h*sy);pc.filter='none';pc.restore();}}
 if($('safe-zones')?.checked){pc.save();pc.fillStyle='#ff4ba52b';pc.fillRect(0,0,pw,ph*.05);pc.fillRect(0,ph*.875,pw,ph*.125);pc.fillRect(pw*.87,ph*.26,pw*.13,ph*.615);pc.restore();}
}
$('top').addEventListener('input',()=>loadNativeLayouts().catch(e=>status(e.message)));
loadNativeLayouts().catch(e=>status(e.message));

async function openSavedClip(file){
 const saved=await request('/clips/'+file+'/edit'),s=saved.settings;
 if(saved.file&&saved.file!==file){swapEditedCards([{previous:file,file:saved.file}]);file=saved.file;}
 document.querySelector('[data-view=editor]').click();
 setSource(saved.source,Number(s.start));setRange(s.start,s.end);savedRange={start:Number(s.start),end:Number(s.end)};rect={cam:{...s.cam},game:{...s.game}};rectEdited=true;layoutClicked=true;
 $('aspect').value=s.aspect||'vertical';$('resolution').value=s.resolution||1080;$('fps').value=s.fps||0;$('top').value=Math.round((s.top||.32)*100);$('edit-top').value=$('top').value;await loadNativeLayouts();setLayout(s.layout||'stack');
 style=s.caption_style||'gta';document.querySelectorAll('[data-style]').forEach(b=>b.classList.toggle('active',b.dataset.style===style));
 $('language').value=s.language||'';if(window.syncLanguagePicker)window.syncLanguagePicker();$('captions').checked=s.captions!==false;$('caption-y').value=s.caption_y||1450;
 $('hook').value=s.hook||'';$('clip-title').value=s.title||'';$('post-caption').value=s.post_caption||'';
 words=s.words||[];wordRange=signature();renderWords();editingClip=file;$('saved-edit').hidden=false;const n=Number(saved.video_clips)||1;$('apply-video').textContent=n>1?'Apply to all '+n+' clips of this video':'Apply to this clip';$('apply-one').hidden=n<=1;
 status(n>1?'Saved clip loaded. Your change will apply to all '+n+' clips of this video (each keeps its own words and title).':'Saved clip loaded. Change framing or captions; saved source and words are reused.');
}
function swapEditedCards(edited){
 for(const e of edited||[]){const olds=[e.previous,...(e.was||[])];const card=[...document.querySelectorAll('.mk')].find(x=>olds.includes(x.dataset.file));if(!card)continue;
  card.dataset.file=e.file;const v=card.querySelector('video');if(v){v.src='/media/'+e.file;v.load();}
  const dl=card.querySelector('a[download]');if(dl){dl.href='/media/'+e.file;dl.download='ninjastudio-'+e.file+'.mp4';}
  const t=card.querySelector('b');if(t&&e.title&&!t.parentElement.classList.contains('viral'))t.textContent=e.title;}
}
async function applySavedEdit(scope){
 if(!editingClip)throw Error('Open Edit clip from My clips first.');
 const settings=exportSettings(id,Number($('start').value),Number($('end').value));
 const changes={};for(const k of ['layout','aspect','resolution','fps','top','cam','game','caption_style','caption_y','captions','hook','title','post_caption'])changes[k]=settings[k];
 const body={file:editingClip,scope,changes};const edited=collectWords();if(edited!==null)body.words=edited;
 const tStart=Number($('start').value),tEnd=Number($('end').value);
 if(savedRange&&(Math.abs(tStart-savedRange.start)>.01||Math.abs(tEnd-savedRange.end)>.01)){
  if(scope!=='one')throw Error('Trimming works on one clip at a time. Press "Only this clip".');
  if(!(tEnd-tStart>=3))throw Error('A clip must be at least 3 seconds long.');
  body.trim={start:tStart,end:tEnd};}
 $('apply-one').disabled=true;$('apply-video').disabled=true;
 try{const {job,clips}=await request('/clips/reedit',body);status('Updating '+clips+' saved clip(s) — no download, AI picking or transcription.');
 for(;;){const result=await request('/status/'+job);status(result.stage||result.status);if(result.status==='error')throw Error(result.error);if(result.status==='done'){swapEditedCards(result.clips);if(result.clips?.length){const changed=result.clips.find(c=>c.previous===editingClip)||result.clips[0];editingClip=changed.file;savedRange={start:Number($('start').value),end:Number($('end').value)};showDownload({file:changed.file,srt:changed.srt});}await refreshLibrary();status(clips+' clip(s) updated in '+result.elapsed_seconds+'s. Source, moments and subtitles reused.');break;}await sleep(500);}}
 finally{$('apply-one').disabled=false;$('apply-video').disabled=false;}
}
$('apply-one').onclick=()=>applySavedEdit('one').catch(e=>status(e.message));
$('apply-video').onclick=()=>applySavedEdit('video').catch(e=>status(e.message));

$('edit-top').addEventListener('input',()=>{$('top').value=$('edit-top').value;loadNativeLayouts().catch(e=>status(e.message));});


// ---- Live clipping (record + chat spikes + backdated clips)
let liveId=null,liveTimer=null;const liveShown=new Set();
function liveStars(d,file){const stars=document.createElement('div');stars.className='stars';const fb=document.createElement('small');fb.className='fb';fb.textContent='Rate this clip ↑';
 for(let n=1;n<=5;n++){const sb=document.createElement('button');sb.textContent='★';sb.setAttribute('aria-label','Rate '+n+' star'+(n===1?'':'s'));sb.onclick=async()=>{try{const r=await request('/feedback',{file,rating:n});[...stars.children].forEach((x,i)=>x.classList.toggle('on',i<n));fb.textContent=ratingMessage(r);}catch(e){fb.textContent=e.message;}};stars.append(sb);}
 d.append(stars,fb);}
function liveCard(c){const d=document.createElement('div');d.className='mk';d.dataset.file=c.file;
 if(c.error){d.textContent='Clip failed: '+c.error;return d;}
 const vid=document.createElement('video');vid.src='/media/'+c.file;vid.controls=true;vid.preload='metadata';
 const t=document.createElement('b');t.textContent=c.title;
 const ax=c.axes||{},f=v=>v==null?'–':v;const vb=document.createElement('div');vb.className='viral';vb.innerHTML='<b>🔥 Viral '+(c.viral??'–')+'</b><span>Chat '+f(ax.chat)+'</span><span>Energy '+f(ax.energy)+'</span><span>Words '+f(ax.words)+'</span><span>AI '+f(ax.ai)+'</span>';
 const m=document.createElement('small');m.textContent=(c.why||'')+(c.hook?' · "'+c.hook+'"':'');
 const a=document.createElement('a');a.href='/media/'+c.file;a.download='ninjastudio-live-'+c.file+'.mp4';a.textContent='Download MP4';
 const edit=document.createElement('button');edit.textContent='Edit clip';edit.onclick=()=>openSavedClip(d.dataset.file).catch(e=>status(e.message));
 d.append(vid,t,vb,m,a,edit);liveStars(d,c.file);return d;}
function liveStatus(s){const mm=String(Math.floor((s.elapsed||0)/60)).padStart(2,'0')+':'+String((s.elapsed||0)%60).padStart(2,'0');
 if(s.status==='error')return '⚠ '+(s.error||'Could not start');
 if(s.status==='starting')return s.stage;
 if(s.status==='recording')return '● Recording '+mm+' · chat '+s.chat_now+' msgs/10 s (normal '+s.baseline+') · chat '+s.chat+' · spikes '+s.spikes+' · clips '+s.clips.length+(s.pending?' · cutting '+s.pending+'…':'');
 return s.stage+' · clips '+s.clips.length;}
async function livePoll(){if(!liveId)return;try{const s=await request('/live/'+liveId);$('live-stats').textContent=liveStatus(s);
 s.clips.forEach((c,i)=>{if(liveShown.has(i))return;liveShown.add(i);$('live-grid').prepend(liveCard(c));});
 if(['stopped','ended','error'].includes(s.status)){clearInterval(liveTimer);liveTimer=null;$('live-start').disabled=false;}}catch(e){$('live-stats').textContent=e.message;clearInterval(liveTimer);$('live-start').disabled=false;}}
$('live-start').onclick=async()=>{const url=$('live-url').value.trim();if(!url){$('live-stats').textContent='Paste a Twitch or YouTube Live link first.';$('live-box').hidden=false;return;}
 $('live-start').disabled=true;$('live-box').hidden=false;$('live-grid').replaceChildren();liveShown.clear();$('live-stats').textContent='Starting the recorder…';
 try{const r=await request('/live/start',{url,layout:makeLayout(),aspect:$('aspect').value,resolution:Number($('resolution').value),fps:Number($('fps').value),cam:rect.cam,game:rect.game,top:Number($('top').value)/100,caption_style:style,language:$('language').value});liveId=r.live;liveTimer=setInterval(livePoll,2000);livePoll();}
 catch(e){$('live-stats').textContent='⚠ '+e.message;$('live-start').disabled=false;if(/already running/.test(e.message)){try{const r=await request('/live-active');if(r.live){liveId=r.live;$('live-start').disabled=true;liveTimer=setInterval(livePoll,2000);livePoll();}}catch(_){}}}};
$('live-now').onclick=async()=>{if(!liveId)return;try{await request('/live/'+liveId+'/clip-now',{});$('live-stats').textContent='Cutting the last 30 s…';}catch(e){$('live-stats').textContent='⚠ '+e.message;}};
$('live-stop').onclick=async()=>{if(!liveId)return;try{await request('/live/'+liveId+'/stop',{});}catch(e){}livePoll();};

// Re-attach to a live session that is already running (after a page reload) so Stop always works.
(async()=>{try{const r=await request('/live-active');if(r.live){liveId=r.live;$('live-box').hidden=false;$('live-start').disabled=true;liveTimer=setInterval(livePoll,2000);livePoll();}}catch(e){}})();

// ---- Creators: a list of streamers that Ninja Studio Clipping watches and clips automatically when they go live.
const creatorOpts=()=>({layout:makeLayout(),aspect:$('aspect').value,resolution:Number($('resolution').value),fps:Number($('fps').value),cam:rect.cam,game:rect.game,top:Number($('top').value)/100,caption_style:style,language:$('language').value});
let creatorSig='';const creatorFeedOpen=new Set();
function attachLive(id){if(liveId===id)return;liveId=id;liveShown.clear();$('live-grid').replaceChildren();$('live-box').hidden=false;$('live-start').disabled=true;clearInterval(liveTimer);liveTimer=setInterval(livePoll,2000);livePoll();}
function agoText(t){if(!t)return 'never';const m=Math.round((Date.now()/1000-t)/60);return m<1?'just now':m<60?m+' min ago':Math.round(m/60)+' h ago';}
function miniCard(clip){const d=document.createElement('div');d.className='mk';d.dataset.file=clip.id;
 const v=document.createElement('video');v.src='/media/'+clip.id;v.controls=true;lazyVideo(v);
 const t=document.createElement('b');t.textContent=clip.title;const m=document.createElement('small');m.textContent=(clip.meta.duration||0).toFixed(0)+' s · '+new Date(clip.created*1000).toLocaleString();
 const a=document.createElement('a');a.href='/media/'+clip.id;a.download='ninjastudio-'+clip.id+'.mp4';a.textContent='Download MP4';
 const e=document.createElement('button');e.textContent='Edit clip';e.onclick=()=>openSavedClip(d.dataset.file).catch(x=>status(x.message));
 d.append(v,t,m,a,e);return d;}
async function fillCreatorFeed(id,grid){const lib=await request('/library');grid.replaceChildren();const mine=lib.filter(c=>(c.settings||{}).creator===id);
 if(!mine.length){const p=document.createElement('small');p.textContent='No clips yet. They appear here by themselves while this creator is live.';grid.append(p);return;}
 mine.forEach(c=>grid.append(miniCard(c)));}
function chipFor(c){const s=document.createElement('span');s.className='chip';
 if(c.status==='recording'){s.classList.add('recording');s.textContent='● Recording & clipping';}
 else if(c.status==='live'&&c.paused_until){s.classList.add('wait');s.textContent='LIVE · paused for '+Math.max(1,Math.round((c.paused_until-Date.now()/1000)/60))+' min (switch Auto off and on to resume now)';}
 else if(c.status==='live'&&c.waiting){s.classList.add('live');s.textContent='LIVE · waiting for the current stream to finish';}
 else if(c.status==='live'){s.classList.add('live');s.textContent=c.auto?'LIVE · starting…':'LIVE now (auto is off)';}
 else if(c.status==='unknown'){s.textContent='Checking…';}
 else{s.textContent='Offline · checked '+agoText(c.checked);}
 return s;}
async function loadCreators(force){
 const r=await request('/creators');
 const sig=JSON.stringify(r.creators.map(c=>[c.id,c.status,c.auto,c.clips,c.waiting,c.session,!!c.paused_until,Math.floor((c.checked||0)/30)]));
 const act=await request('/live-active').catch(()=>({}));if(act.live&&!liveId)attachLive(act.live);
 if(!force&&sig===creatorSig)return;creatorSig=sig;
 const host=$('creator-list');host.replaceChildren();
 if(!r.creators.length){const p=document.createElement('p');p.className='muted';p.textContent='No creators yet. Add a streamer above and Ninja Studio Clipping will clip them whenever they go live.';host.append(p);return;}
 for(const c of r.creators){
  const row=document.createElement('div');row.className='creator-row';
  const top=document.createElement('div');top.className='creator-top';
  const nm=document.createElement('b');nm.textContent=c.name;const pl=document.createElement('span');pl.className='plat';pl.textContent=c.platform;
  const lab=document.createElement('label');const cb=document.createElement('input');cb.type='checkbox';cb.checked=!!c.auto;
  cb.onchange=()=>request('/creators/'+c.id+'/auto',{auto:cb.checked}).then(()=>loadCreators(true)).catch(e=>status(e.message));
  lab.append(cb,document.createTextNode('Auto-clip when live'));top.append(nm,pl,chipFor(c),lab);
  const acts=document.createElement('div');acts.className='creator-actions';
  const mk=(txt,fn)=>{const b=document.createElement('button');b.className='secondary';b.textContent=txt;b.onclick=()=>fn(b).catch(e=>{$('creator-note').textContent='⚠ '+e.message;});acts.append(b);return b;};
  mk('Check now',async b=>{b.disabled=true;$('creator-note').textContent='Checking '+c.name+'…';const x=await request('/creators/'+c.id+'/check',{});$('creator-note').textContent=c.name+(x.live?' is live right now.':' is not live right now.');await loadCreators(true);});
  mk('Use my current layout',async()=>{await request('/creators/'+c.id+'/layout',creatorOpts());$('creator-note').textContent='Saved your current layout, facecam boxes and caption style for '+c.name+'.';});
  if(c.session)mk('Open live view',async()=>{attachLive(c.session);$('live-box').scrollIntoView({behavior:'smooth'});});
  mk('Remove',async()=>{if(!confirm('Remove '+c.name+' from your list? Their clips stay in My clips.'))return;await request('/creators/'+c.id+'/remove',{});await loadCreators(true);});
  const det=document.createElement('details');det.className='creator-feed';const sm=document.createElement('summary');sm.textContent='Clips from '+c.name+' ('+c.clips+')';const grid=document.createElement('div');grid.className='make-grid';
  det.append(sm,grid);det.open=creatorFeedOpen.has(c.id);if(det.open)fillCreatorFeed(c.id,grid).catch(()=>{});
  det.ontoggle=()=>{if(det.open){creatorFeedOpen.add(c.id);fillCreatorFeed(c.id,grid).catch(()=>{});}else creatorFeedOpen.delete(c.id);};
  row.append(top,acts,det);host.append(row);}
}
$('creator-add').onclick=async()=>{const url=$('creator-url').value.trim();if(!url){$('creator-note').textContent='Type a Twitch name or paste a channel link first.';return;}
 try{await request('/creators',{url,...creatorOpts()});$('creator-url').value='';$('creator-note').textContent='Added. Checking if they are live…';await loadCreators(true);}catch(e){$('creator-note').textContent='⚠ '+e.message;}};
loadCreators(true).catch(()=>{});setInterval(()=>{if(!document.hidden)loadCreators().catch(()=>{});},8000);

$('download-bundle').onclick=async()=>{try{if(!editingClip)throw Error('Open a saved clip first.');status('Preparing this video’s saved clips — no rendering.');const result=await request('/bundles',{file:editingClip,scope:'video'});const link=$('bundle-link');link.href=result.download;link.hidden=false;link.textContent='Download '+result.clips+' clips + subtitles ZIP';status('Bundle ready. Original MP4s, subtitles and post copy are included.');}catch(e){status(e.message);}};

let queuePaused=false;
async function refreshQueue(){const result=await request('/queue');queuePaused=result.paused;$('queue-pause').textContent=queuePaused?'Resume queue':'Pause queue';const host=$('queue-list');host.replaceChildren();for(const row of result.jobs){const card=document.createElement('div');card.className='queue-item';const title=document.createElement('b');title.textContent=row.kind+' · '+(row.payload.url||row.payload.id||'Saved clip');const detail=document.createElement('small');detail.textContent=row.status+(row.result.stage?' · '+row.result.stage:'')+(row.result.error?' · '+row.result.error:'');card.append(title,detail);if(['error','interrupted','canceled'].includes(row.status)){const button=document.createElement('button');button.textContent='Retry';button.onclick=async()=>{await request('/queue/'+row.id+'/retry',{});refreshQueue();};card.append(button);}if(row.status==='queued'){const button=document.createElement('button');button.textContent='Cancel waiting job';button.onclick=async()=>{await request('/queue/'+row.id+'/cancel',{});refreshQueue();};card.append(button);}host.append(card);}}
$('queue-add').onclick=async()=>{try{const urls=$('queue-urls').value.split(/\n/).map(x=>x.trim()).filter(Boolean);if(!urls.length)throw Error('Paste at least one video link.');for(const url of urls){await request('/queue',{kind:'make',not_before:$('queue-time').value?new Date($('queue-time').value).getTime()/1000:0,payload:{url,count:Number($('count').value),mode:$('mode').value,source_height:Number(($('srcq')||{}).value)||1080,accurate:$('accurate').value,min_len:Number($('minlen').value),max_len:Number($('length').value),...creatorOpts()}});}status(urls.length+' video(s) saved to the local processing queue.');await refreshQueue();}catch(e){status(e.message);}};
$('queue-pause').onclick=async()=>{try{await request('/queue/pause',{paused:!queuePaused});await refreshQueue();}catch(e){status(e.message);}};
$('queue-refresh').onclick=()=>refreshQueue().catch(e=>status(e.message));
$('queue-panel').addEventListener('toggle',()=>{if($('queue-panel').open)refreshQueue().catch(e=>status(e.message));});
setInterval(()=>{if($('queue-panel').open)refreshQueue().catch(()=>{});},2000);

for(const key of ['aspect','resolution'])$(key).addEventListener('change',()=>loadNativeLayouts().catch(e=>status(e.message)));

$('timing-editor').onchange=renderWords;
$('shift-captions').onclick=()=>{try{const current=collectWords();if(!current?.length)throw Error('Generate or import subtitles first.');const offset=Number($('caption-shift').value);if(!Number.isFinite(offset))throw Error('Choose a valid shift.');const shifted=current.map(w=>({...w,start:w.start+offset,end:w.end+offset}));const duration=Number($('end').value)-Number($('start').value);if(shifted.some(w=>w.start<0||w.end>duration+.1))throw Error('That shift places words outside the clip. Choose a smaller shift.');words=shifted;renderWords();status('Subtitle times shifted by '+offset+' seconds. Apply or export to update the video.');}catch(e){status(e.message);}};

fetch('/healthz').then(r=>r.json()).then(h=>{if(h&&h.ffmpeg===false){const m='FFmpeg is not installed on this computer, so clips cannot be made. Install it with: winget install Gyan.FFmpeg';status(m);const n=document.getElementById("link-status");if(n)n.textContent=m;}}).catch(()=>{});



function camFilter(){const g=k=>Number(document.getElementById('cam-'+k)?.value);const c=g('contrast')||1,b=g('brightness')||0,s=isNaN(g('saturation'))?1:g('saturation'),k=g('clarity')||0;return `contrast(${c}) brightness(${1+b}) saturate(${s})`+(k>0.05?` contrast(${1+k*0.12})`:'');}
['contrast','brightness','saturation','clarity'].forEach(k=>{const el=document.getElementById('cam-'+k);if(!el)return;const out=document.getElementById('cam-'+k+'-o');const show=()=>{if(out)out.textContent=Number(el.value).toFixed(2);};el.addEventListener('input',()=>{show();if(typeof paint==='function')paint();});show();});
const camReset=document.getElementById('cam-reset');if(camReset)camReset.onclick=()=>{const d={contrast:1,brightness:0,saturation:1,clarity:0};for(const k in d){const el=document.getElementById('cam-'+k);if(el){el.value=d[k];el.dispatchEvent(new Event('input'));}}};
