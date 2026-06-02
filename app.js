/* Agent Velocity — leaderboard render from data.json */
(function(){
  "use strict";
  var W=window;
  var nav=document.getElementById("nav");
  if(nav){var on=function(){nav.classList.toggle("scrolled",W.scrollY>20)};W.addEventListener("scroll",on,{passive:true});on();}

  var ALL=[], state={cat:"All", sortKey:"momentum", sortDir:"desc"};
  function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c];});}
  function fmtStars(n){return n>=1000?(n/1000).toFixed(n>=10000?0:1).replace(/\.0$/,"")+"k":String(n);}
  function relDate(iso){if(!iso)return"recently";var d=(Date.now()-new Date(iso).getTime())/86400000;if(isNaN(d))return"recently";if(d<1)return"today";if(d<2)return"1d ago";if(d<30)return Math.round(d)+"d ago";if(d<365)return Math.round(d/30)+"mo ago";return Math.round(d/365)+"y ago";}
  function safeUrl(u){if(!u)return null;try{var p=new URL(u,location.href).protocol;return(p==="http:"||p==="https:")?u:null;}catch(e){return null;}}
  /* slug = lowercase url-safe owner-name (must match build_data.py slugify) */
  function slugify(s){return String(s==null?"":s).toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-+|-+$/g,"");}
  function detailUrl(r){return "/a/"+slugify(r.owner+"-"+r.name)+"/";}
  function spark(arr,w,h){
    if(!arr||arr.length<2)return'<div class="spark"><span class="ph">—</span></div>';
    var mx=Math.max.apply(null,arr),mn=Math.min.apply(null,arr),rg=(mx-mn)||1,n=arr.length,pad=2;
    var pts=arr.map(function(v,i){return (pad+i*(w-2*pad)/(n-1)).toFixed(1)+","+(h-pad-((v-mn)/rg)*(h-2*pad)).toFixed(1);}).join(" ");
    var lx=(w-pad).toFixed(1),ly=(h-pad-((arr[n-1]-mn)/rg)*(h-2*pad)).toFixed(1);
    return '<svg class="spark" viewBox="0 0 '+w+' '+h+'" preserveAspectRatio="none" aria-hidden="true"><polyline points="'+pts+'" fill="none" stroke="#ff8a2b" stroke-width="1.4" stroke-linejoin="round"/><circle cx="'+lx+'" cy="'+ly+'" r="2" fill="#ff4324"/></svg>';
  }
  function trend(d){if(d>3)return'<span class="t up">▲ '+d+'/mo</span>';if(d<-3)return'<span class="t dn">▼ '+Math.abs(d)+'/mo</span>';return'<span class="t flat">→ steady</span>';}
  function m(v,l){return'<div class="m"><b>'+esc(v)+'</b><span>'+esc(l)+'</span></div>';}

  function rowsFor(list){
    return list.map(function(r){
      var rel=r.last_release?'<div class="rel">'+esc(r.last_release)+' · '+relDate(r.last_release_at)+'</div>':'';
      var v=r.recent4w_commits>=3000?"3000+":r.recent4w_commits;
      return '<a class="lrow" href="'+esc(detailUrl(r))+'">'
        +'<span class="lrank '+(r.rank<=3?"t"+r.rank:"")+'">'+r.rank+'</span>'
        +'<div class="lname"><h3>'+esc(r.name)+' <span class="cat">'+esc(r.category)+'</span></h3>'
          +'<p>'+esc(r.blurb)+'</p>'+rel+'</div>'
        +'<div class="vel"><div class="bar"><i style="width:'+r.momentum+'%"></i></div><div class="v"><b>'+r.momentum+'</b><span>'+v+' commits/mo</span></div></div>'
        +'<div>'+spark(r.monthly_commits,130,34)+'</div>'
        +'<div class="lstars"><b>'+fmtStars(r.stars)+'</b>'+trend(r.commit_delta)+'</div></a>';
    }).join("");
  }
  function sortList(list){
    var k=state.sortKey, dir=state.sortDir==="asc"?1:-1;
    return list.slice().sort(function(a,b){
      var av=a[k]==null?-Infinity:a[k], bv=b[k]==null?-Infinity:b[k];
      if(av<bv)return -1*dir; if(av>bv)return 1*dir;
      return a.rank-b.rank; /* stable tiebreak by rank */
    });
  }
  function render(){
    var list=state.cat==="All"?ALL:ALL.filter(function(r){return r.category===state.cat;});
    list=sortList(list);
    document.getElementById("lboard").innerHTML = list.length?rowsFor(list):'<div class="loading">No agents in this category.</div>';
  }

  var SORT_LABELS={momentum:"velocity", recent4w_commits:"commits", stars:"stars"};
  function applySortUI(){
    var note=document.getElementById("sortnote");
    if(note)note.textContent="Ranked by "+(SORT_LABELS[state.sortKey]||state.sortKey)+" "+(state.sortDir==="asc"?"↑":"↓");
    document.querySelectorAll(".bhead .sortable").forEach(function(h){
      var k=h.getAttribute("data-sort"), active=k===state.sortKey;
      h.setAttribute("aria-sort", active?(state.sortDir==="asc"?"ascending":"descending"):"none");
      var ar=h.querySelector(".arrow"); if(ar)ar.textContent=(active&&state.sortDir==="asc")?"▲":"▼";
    });
  }
  function clickSort(h){
    var k=h.getAttribute("data-sort"); if(!k)return;
    if(state.sortKey===k){ state.sortDir=state.sortDir==="asc"?"desc":"asc"; }
    else { state.sortKey=k; state.sortDir="desc"; } /* new column defaults desc */
    applySortUI(); render();
  }
  function wireSort(){
    document.querySelectorAll(".bhead .sortable").forEach(function(h){
      h.addEventListener("click",function(){clickSort(h);});
      h.addEventListener("keydown",function(e){if(e.key==="Enter"||e.key===" "){e.preventDefault();clickSort(h);}});
    });
    applySortUI();
  }

  function injectItemList(list){
    var el=document.getElementById("itemlist-ld"); if(!el)return;
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
    document.getElementById("metarow").innerHTML =
      m(data.repo_count,"Agents tracked")+m(fmtStars(totalStars),"Combined stars")
      +m(ALL.length?ALL[0].momentum:0,"Top velocity")+m(mover?mover.name:"—","Biggest mover");
    document.getElementById("liveline").textContent="The coding-agent race · recomputed "+relDate(data.generated_at);
    var fg=document.getElementById("footgen");if(fg)fg.textContent="Recomputed "+relDate(data.generated_at);

    // podium top 3 — internal links to detail pages
    var medals=["①","②","③"], pclass=["p1","p2","p3"];
    document.getElementById("podium").innerHTML = ALL.slice(0,3).map(function(r,i){
      return '<a class="pod '+pclass[i]+'" href="'+esc(detailUrl(r))+'">'
        +'<div class="pr"><span class="medal">'+medals[i]+'</span> #'+(i+1)+' · '+esc(r.category)+'</div>'
        +'<h3>'+esc(r.name)+'</h3><div class="vel" style="color:var(--hot-2);font-family:var(--mono);font-size:12px;font-weight:500">velocity '+r.momentum+' · '+r.recent4w_commits+' commits/mo</div>'
        +'<p>'+esc(r.blurb)+'</p></a>';
    }).join("");

    var cats=["All"].concat(data.categories||[]);
    document.getElementById("filters").innerHTML=cats.map(function(c,i){return '<button class="chip'+(i===0?" active":"")+'" data-cat="'+esc(c)+'" aria-pressed="'+(i===0)+'">'+esc(c)+'</button>';}).join("");
    var chips=document.querySelectorAll(".chip");
    chips.forEach(function(c){c.addEventListener("click",function(){chips.forEach(function(x){var on=x===c;x.classList.toggle("active",on);x.setAttribute("aria-pressed",on);});state.cat=c.getAttribute("data-cat");render();});});

    wireSort();
    injectItemList(ALL);
    render();
  }
  fetch("data.json",{cache:"no-store"}).then(function(r){return r.json();}).then(build).catch(function(e){
    document.getElementById("lboard").innerHTML='<div class="loading">Could not load. '+esc(e.message||e)+'</div>';
  });
})();
