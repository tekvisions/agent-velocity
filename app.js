/* Agent Velocity — leaderboard render from data.json. Vanilla, no deps. */
(function(){
  "use strict";
  var W=window, D=document;
  var RM = W.matchMedia && W.matchMedia("(prefers-reduced-motion:reduce)").matches;
  var nav=D.getElementById("nav");
  if(nav){var on=function(){nav.classList.toggle("scrolled",W.scrollY>20)};W.addEventListener("scroll",on,{passive:true});on();}

  var ALL=[], state={cat:"All", q:"", sortKey:"momentum", sortDir:"desc"};
  function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];});}
  function fmtStars(n){return n>=1000?(n/1000).toFixed(n>=10000?0:1).replace(/\.0$/,"")+"k":String(n);}
  function fmtInt(n){return String(n).replace(/\B(?=(\d{3})+(?!\d))/g,",");}
  function relDate(iso){if(!iso)return"recently";var d=(Date.now()-new Date(iso).getTime())/86400000;if(isNaN(d))return"recently";if(d<1)return"today";if(d<2)return"1d ago";if(d<30)return Math.round(d)+"d ago";if(d<365)return Math.round(d/30)+"mo ago";return Math.round(d/365)+"y ago";}
  /* slug = lowercase url-safe owner-name (must match build_data.py slugify) */
  function slugify(s){return String(s==null?"":s).toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"");}
  function detailUrl(r){return "/a/"+slugify(r.owner+"-"+r.name)+"/";}

  /* race posture: who's accelerating vs coasting vs braking — the velocity motif */
  function posture(r){
    var d=r.commit_delta||0, prior=r.prior4w_commits||0;
    var pct = prior>0 ? d/prior : (r.recent4w_commits>0?1:0);
    if(d>3 && pct>=0.12) return {k:"surge", label:"Accelerating", icon:"▲"};
    if(d>3) return {k:"up", label:"Gaining", icon:"▲"};
    if(d<-3 && pct<=-0.12) return {k:"brake", label:"Braking", icon:"▼"};
    if(d<-3) return {k:"down", label:"Easing", icon:"▼"};
    return {k:"flat", label:"Holding", icon:"→"};
  }
  function trend(r){var p=posture(r);var amt=Math.abs(r.commit_delta||0);
    var t=p.k==="flat"?"steady":(amt+"/mo");
    return '<span class="t '+(p.k==="surge"||p.k==="up"?"up":p.k==="flat"?"flat":"dn")+'" title="'+p.label+' — '+(r.commit_delta>0?"+":"")+(r.commit_delta||0)+' commits vs prior 4 weeks">'+p.icon+' '+t+'</span>';}

  /* highlight matched query inside an escaped string */
  function hi(text){
    var s=esc(text); if(!state.q) return s;
    var q=state.q.replace(/[.*+?^${}()|[\]\\]/g,"\\$&");
    try{ return s.replace(new RegExp("("+q+")","ig"), '<mark>$1</mark>'); }catch(e){ return s; }
  }

  function spark(arr,w,h){
    if(!arr||arr.length<2)return'<div class="spark"><span class="ph">—</span></div>';
    var mx=Math.max.apply(null,arr),mn=Math.min.apply(null,arr),rg=(mx-mn)||1,n=arr.length,pad=2;
    var pts=arr.map(function(v,i){return (pad+i*(w-2*pad)/(n-1)).toFixed(1)+","+(h-pad-((v-mn)/rg)*(h-2*pad)).toFixed(1);}).join(" ");
    var lx=(w-pad).toFixed(1),ly=(h-pad-((arr[n-1]-mn)/rg)*(h-2*pad)).toFixed(1);
    /* per-point dots carry the value for the hover tooltip */
    var dots=arr.map(function(v,i){
      var cx=(pad+i*(w-2*pad)/(n-1)).toFixed(1), cy=(h-pad-((v-mn)/rg)*(h-2*pad)).toFixed(1);
      var mo=n-1-i; var lbl=mo===0?"this month":(mo+"mo ago");
      return '<circle class="sd" cx="'+cx+'" cy="'+cy+'" r="6" data-v="'+v+'" data-when="'+lbl+'"></circle>';
    }).join("");
    return '<svg class="spark" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none" aria-hidden="true">'
      +'<polyline points="'+pts+'" fill="none" stroke="#ff8a2b" stroke-width="1.4" stroke-linejoin="round"/>'
      +'<circle cx="'+lx+'" cy="'+ly+'" r="2" fill="#ff4324"/>'+dots+'</svg>';
  }
  function m(v,l,num){return'<div class="m"><b'+(num?' data-count="'+num+'"':'')+'>'+esc(v)+'</b><span>'+esc(l)+'</span></div>';}

  /* position movement vs the prior daily run: ▲N climbed, ▼N slipped, → held, • new.
     rank_delta>0 means a smaller (better) rank number — i.e. climbed the board. */
  function moveBadge(r){
    var d=r.rank_delta;
    if(d==null) return '';  /* no prior history yet — show nothing (fills in daily) */
    if(d>0) return '<span class="mv up" title="Climbed '+d+' since the prior run">▲'+d+'</span>';
    if(d<0) return '<span class="mv dn" title="Slipped '+Math.abs(d)+' since the prior run">▼'+Math.abs(d)+'</span>';
    return '<span class="mv flat" title="Held position">→</span>';
  }

  function rowsFor(list){
    return list.map(function(r){
      var rel=r.last_release?'<div class="rel" title="Latest stable release">'+esc(r.last_release)+' · '+relDate(r.last_release_at)+'</div>':'';
      var v=r.recent4w_commits>=3000?"3000+":r.recent4w_commits;
      var p=posture(r);
      return '<a class="lrow" href="'+esc(detailUrl(r))+'" data-slug="'+esc(slugify(r.owner+"-"+r.name))+'" data-posture="'+p.k+'" aria-label="'+esc(r.name)+', rank '+r.rank+', velocity '+r.momentum+', '+p.label+'">'
        +'<span class="lrank '+(r.rank<=3?"t"+r.rank:"")+'">'+r.rank+moveBadge(r)+'</span>'
        +'<div class="lname"><h3>'+hi(r.name)+' <span class="owner">'+hi(r.owner)+'</span> <span class="cat">'+esc(r.category)+'</span></h3>'
          +'<p>'+hi(r.blurb)+'</p>'+rel+'</div>'
        +'<div class="vel"><div class="bar" data-w="'+r.momentum+'"><i style="width:0%"></i></div><div class="v"><b>'+r.momentum+'</b><span>'+v+' commits/mo</span></div></div>'
        +'<div class="sparkcell">'+spark(r.monthly_commits,130,34)+'</div>'
        +'<div class="lstars"><b>'+fmtStars(r.stars)+'</b>'+trend(r)+'</div></a>';
    }).join("");
  }

  function sortList(list){
    var k=state.sortKey, dir=state.sortDir==="asc"?1:-1;
    return list.slice().sort(function(a,b){
      var av,bv;
      if(k==="name"){ av=String(a.name||"").toLowerCase(); bv=String(b.name||"").toLowerCase();
        if(av<bv)return -1*dir; if(av>bv)return 1*dir; return a.rank-b.rank; }
      av=a[k]==null?-Infinity:a[k]; bv=b[k]==null?-Infinity:b[k];
      if(av<bv)return -1*dir; if(av>bv)return 1*dir;
      return a.rank-b.rank; /* stable tiebreak by canonical rank */
    });
  }
  function matchQ(r){
    if(!state.q) return true;
    var q=state.q.toLowerCase();
    return (r.name+" "+r.owner+" "+r.category+" "+(r.language||"")+" "+(r.blurb||"")).toLowerCase().indexOf(q)>=0;
  }
  function currentList(){
    var list=ALL.filter(function(r){return (state.cat==="All"||r.category===state.cat) && matchQ(r);});
    return sortList(list);
  }

  /* FLIP: animate rows from their previous box to the new one after a re-render */
  function snapshot(board){
    var map={};
    Array.prototype.forEach.call(board.querySelectorAll(".lrow"),function(el){
      map[el.getAttribute("data-slug")]=el.getBoundingClientRect();
    });
    return map;
  }
  function flip(board, prev){
    if(RM) return;
    Array.prototype.forEach.call(board.querySelectorAll(".lrow"),function(el){
      var slug=el.getAttribute("data-slug"), before=prev[slug];
      if(!before) return;
      var after=el.getBoundingClientRect();
      var dy=before.top-after.top;
      if(Math.abs(dy)<1) return;
      el.style.transform="translateY("+dy+"px)";
      el.style.transition="none";
      el.getBoundingClientRect(); /* force reflow */
      el.style.transition="transform .5s cubic-bezier(.2,.7,.2,1)";
      el.style.transform="";
    });
    setTimeout(function(){ Array.prototype.forEach.call(board.querySelectorAll(".lrow"),function(el){el.style.transition="";}); },560);
  }

  function animateBars(board){
    var bars=board.querySelectorAll(".vel .bar i");
    requestAnimationFrame(function(){ requestAnimationFrame(function(){
      Array.prototype.forEach.call(bars,function(i){
        var w=i.parentNode.getAttribute("data-w")||0;
        i.style.width=w+"%"; /* CSS transition animates it; killed under reduced-motion */
      });
    }); });
  }

  function render(opts){
    var board=D.getElementById("lboard");
    var prev = (opts&&opts.flip&&!RM)?snapshot(board):null;
    var list=currentList();
    if(!list.length){
      board.innerHTML='<div class="empty"><span class="big">No agents match.</span>'
        +(state.q?'<span class="sub">Nothing for “'+esc(state.q)+'”'+(state.cat!=="All"?" in "+esc(state.cat):"")+'.</span><button class="resetbtn" id="resetfilters" type="button">Clear filters</button>':'<span class="sub">Try another category.</span>')+'</div>';
      var rb=D.getElementById("resetfilters"); if(rb)rb.addEventListener("click",resetFilters);
      updateCount(0);
      return;
    }
    var reRender = !!(opts&&opts.flip);
    board.classList.toggle("static", reRender); /* re-render: skip entrance anim, FLIP owns motion */
    board.innerHTML=rowsFor(list);
    if(reRender){
      if(prev) flip(board, prev);
    } else if(!RM){
      stagger(board); /* first paint: set --d so the CSS entrance animation cascades */
    }
    animateBars(board);
    updateCount(list.length);
  }

  function updateCount(n){
    var el=D.getElementById("resultcount"); if(!el)return;
    var total=ALL.length;
    el.textContent = (n===total) ? total+" agents" : n+" of "+total+" shown";
  }

  /* first-paint stagger: set a per-row delay so the CSS entrance animation cascades.
     The animation self-completes to opacity:1, so rows are never left hidden. */
  function stagger(board){
    Array.prototype.forEach.call(board.querySelectorAll(".lrow"),function(el,i){
      el.style.setProperty("--d",(Math.min(i,12)*36)+"ms");
    });
  }

  var SORT_LABELS={momentum:"velocity", recent4w_commits:"commits", stars:"stars", name:"name"};
  function applySortUI(){
    var note=D.getElementById("sortnote");
    if(note){ var asc=state.sortDir==="asc";
      note.textContent=(state.sortKey==="name"?"A–Z by name ":"Ranked by "+(SORT_LABELS[state.sortKey]||state.sortKey)+" ")+(state.sortKey==="name"?(asc?"↓":"↑"):(asc?"↑":"↓"));
    }
    D.querySelectorAll(".bhead .sortable").forEach(function(h){
      var k=h.getAttribute("data-sort"), active=k===state.sortKey;
      h.setAttribute("aria-sort", active?(state.sortDir==="asc"?"ascending":"descending"):"none");
      h.classList.toggle("on",active);
      var ar=h.querySelector(".arrow"); if(ar)ar.textContent=(active&&state.sortDir==="asc")?"▲":"▼";
    });
  }
  function clickSort(h){
    var k=h.getAttribute("data-sort"); if(!k)return;
    if(state.sortKey===k){ state.sortDir=state.sortDir==="asc"?"desc":"asc"; }
    else { state.sortKey=k; state.sortDir = k==="name"?"asc":"desc"; } /* name defaults A→Z, metrics default high→low */
    applySortUI(); render({flip:true});
  }
  function wireSort(){
    D.querySelectorAll(".bhead .sortable").forEach(function(h){
      h.addEventListener("click",function(){clickSort(h);});
      h.addEventListener("keydown",function(e){if(e.key==="Enter"||e.key===" "){e.preventDefault();clickSort(h);}});
    });
    applySortUI();
  }

  function resetFilters(){
    state.cat="All"; state.q="";
    var si=D.getElementById("search"); if(si)si.value="";
    var sc=D.getElementById("searchclear"); if(sc)sc.hidden=true;
    D.querySelectorAll(".chip").forEach(function(x){var on=x.getAttribute("data-cat")==="All";x.classList.toggle("active",on);x.setAttribute("aria-pressed",on);});
    render({flip:true});
  }

  function wireSearch(){
    var si=D.getElementById("search"), sc=D.getElementById("searchclear"); if(!si)return;
    var t;
    function run(){ state.q=si.value.trim(); if(sc)sc.hidden=!si.value; render({flip:true}); }
    si.addEventListener("input",function(){ clearTimeout(t); t=setTimeout(run,90); });
    si.addEventListener("keydown",function(e){ if(e.key==="Escape"){ si.value=""; run(); si.blur(); } });
    if(sc)sc.addEventListener("click",function(){ si.value=""; run(); si.focus(); });
    /* "/" focuses search, like a real leaderboard */
    D.addEventListener("keydown",function(e){
      if(e.key==="/" && D.activeElement!==si && !/^(INPUT|TEXTAREA)$/.test((D.activeElement||{}).tagName||"")){ e.preventDefault(); si.focus(); }
    });
  }

  /* sparkline tooltip — one shared bubble, delegated over the board */
  function wireSparkTips(){
    var board=D.getElementById("lboard"); if(!board)return;
    var tip=D.createElement("div"); tip.className="sparktip"; tip.setAttribute("role","tooltip"); tip.hidden=true;
    D.body.appendChild(tip);
    board.addEventListener("mouseover",function(e){
      var dot=e.target.closest&&e.target.closest(".sd"); if(!dot)return;
      var v=dot.getAttribute("data-v"), when=dot.getAttribute("data-when");
      tip.innerHTML='<b>'+esc(fmtInt(+v))+'</b> commits<span>'+esc(when)+'</span>'; tip.hidden=false;
      var rc=dot.getBoundingClientRect();
      tip.style.left=(rc.left+rc.width/2)+"px"; tip.style.top=(rc.top-10)+"px";
    });
    board.addEventListener("mouseout",function(e){ if(e.target.closest&&e.target.closest(".sd")) tip.hidden=true; });
    board.addEventListener("click",function(){ tip.hidden=true; },true);
  }

  /* count-up for the hero meta numbers (initial paint only) */
  function countUp(){
    if(RM){ D.querySelectorAll("[data-count]").forEach(function(el){el.textContent=el.getAttribute("data-orig")||el.textContent;}); return; }
    D.querySelectorAll("[data-count]").forEach(function(el){
      var target=+el.getAttribute("data-count"); if(!isFinite(target)){return;}
      var suffix=el.getAttribute("data-suffix")||"", dur=900, t0=null;
      function step(ts){ if(!t0)t0=ts; var p=Math.min((ts-t0)/dur,1); var e=1-Math.pow(1-p,3);
        var val=Math.round(target*e); el.textContent=(val>=1000?fmtStars(val):val)+suffix;
        if(p<1)requestAnimationFrame(step); else el.textContent=el.getAttribute("data-orig"); }
      requestAnimationFrame(step);
    });
  }

  function injectItemList(list){
    var el=D.getElementById("itemlist-ld"); if(!el)return;
    var base="https://agentvelocity.kymatalabs.com";
    var ld={"@context":"https://schema.org","@type":"ItemList",
      "name":"Open-source coding agents ranked by shipping velocity",
      "itemListOrder":"https://schema.org/ItemListOrderDescending",
      "numberOfItems":list.length,
      "itemListElement":list.map(function(r,i){
        return {"@type":"ListItem","position":i+1,"url":base+detailUrl(r),"name":r.owner+"/"+r.name};
      })};
    el.textContent=JSON.stringify(ld);
  }

  function build(data){
    ALL=data.repos||[];
    var totalStars=ALL.reduce(function(a,r){return a+r.stars;},0);
    var mover=ALL.slice().sort(function(a,b){return b.commit_delta-a.commit_delta;})[0];
    var topV=ALL.length?ALL[0].momentum:0;
    /* meta row with count-up: store the display string in data-orig, the numeric target in data-count */
    var mr=D.getElementById("metarow");
    mr.innerHTML =
      mCount(data.repo_count, data.repo_count, "Agents tracked")
      +mCount(fmtStars(totalStars), totalStars, "Combined stars")
      +mCount(topV, topV, "Top velocity")
      +m(mover?mover.name:"—","Biggest mover");
    D.getElementById("liveline").textContent="The coding-agent race · recomputed "+relDate(data.generated_at);
    var fg=D.getElementById("footgen");if(fg)fg.textContent="Recomputed "+relDate(data.generated_at);

    // podium top 3 — internal links to detail pages
    var medals=["①","②","③"], pclass=["p1","p2","p3"];
    D.getElementById("podium").innerHTML = ALL.slice(0,3).map(function(r,i){
      var p=posture(r);
      return '<a class="pod '+pclass[i]+'" href="'+esc(detailUrl(r))+'">'
        +'<div class="pr"><span class="medal">'+medals[i]+'</span> #'+(i+1)+' · '+esc(r.category)+'</div>'
        +'<h3>'+esc(r.name)+'</h3>'
        +'<div class="podvel"><span class="pv">velocity '+r.momentum+'</span><span class="pp '+p.k+'">'+p.icon+' '+esc(p.label)+'</span></div>'
        +'<div class="podmeter"><i style="width:'+r.momentum+'%"></i></div>'
        +'<p>'+esc(r.blurb)+'</p></a>';
    }).join("");

    // movers strip — biggest climbers since the prior run (rank_delta), or top
    // commit-surge repos on day one before position history exists.
    renderMovers(data.movers||[]);

    var cats=["All"].concat(data.categories||[]);
    D.getElementById("filters").innerHTML=cats.map(function(c,i){
      var n=c==="All"?ALL.length:ALL.filter(function(r){return r.category===c;}).length;
      return '<button class="chip'+(i===0?" active":"")+'" data-cat="'+esc(c)+'" aria-pressed="'+(i===0)+'">'+esc(c)+'<span class="cn">'+n+'</span></button>';
    }).join("");
    var chips=D.querySelectorAll(".chip");
    chips.forEach(function(c){c.addEventListener("click",function(){chips.forEach(function(x){var onn=x===c;x.classList.toggle("active",onn);x.setAttribute("aria-pressed",onn);});state.cat=c.getAttribute("data-cat");render({flip:true});});});

    wireSort();
    wireSearch();
    injectItemList(ALL);
    render();
    countUp();
    wireSparkTips();
    /* podium meters fill in after paint */
    requestAnimationFrame(function(){requestAnimationFrame(function(){
      D.querySelectorAll(".podmeter i").forEach(function(i){var w=i.style.width;i.style.width="0";i.getBoundingClientRect();i.style.transition="width .9s cubic-bezier(.2,.7,.2,1)";i.style.width=w;});
    });});
  }

  /* movers strip: horizontally-scrollable chips linking to detail pages. Each shows
     the position climb (▲N) when tracked, else the commit surge (+N commits/mo). */
  function renderMovers(movers){
    var el=D.getElementById("movers"); if(!el) return;
    if(!movers.length){ el.hidden=true; return; }
    var chips=movers.map(function(m,i){
      var climbed=(typeof m.rank_delta==="number" && m.rank_delta>0);
      var tag=climbed
        ? '<span class="mv up">▲'+m.rank_delta+'</span>'
        : '<span class="mv up">+'+(m.commit_delta||0)+'</span>';
      var sub=climbed?("now #"+m.rank):((m.commit_delta||0)+" commits/mo");
      return '<a class="mover" href="/a/'+esc(slugify(m.owner+"-"+m.name))+'/" style="--d:'+(i*50)+'ms">'
        +tag+'<span class="mvn">'+esc(m.name)+'</span><span class="mvs">'+esc(sub)+'</span></a>';
    }).join("");
    el.innerHTML='<span class="movers-l">Movers</span><div class="movers-track">'+chips+'</div>';
    el.hidden=false;
  }

  /* meta cell that count-ups: keep the final display string, expose the numeric target */
  function mCount(display, num, label){
    return '<div class="m"><b data-count="'+num+'" data-orig="'+esc(display)+'">'+esc(display)+'</b><span>'+esc(label)+'</span></div>';
  }

  fetch("data.json",{cache:"no-store"}).then(function(r){return r.json();}).then(build).catch(function(e){
    D.getElementById("lboard").innerHTML='<div class="loading">Could not load. '+esc(e.message||e)+'</div>';
  });
})();
