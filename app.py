from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, quote
from urllib.request import Request, urlopen
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
import sqlite3, json, threading, time, os, hashlib, re

ROOT=Path(__file__).parent; STATIC=ROOT/'static'; DATA=ROOT/'data'; DATA.mkdir(exist_ok=True); DB=DATA/'crownwatch.db'
TOKEN=os.getenv('CLASH_ROYALE_TOKEN','').strip(); PORT=int(os.getenv('CROWNWATCH_PORT','8787'))
POLL=max(5,int(os.getenv('CROWNWATCH_POLL_MINUTES','60'))); PLAYERS=max(5,min(75,int(os.getenv('CROWNWATCH_META_PLAYERS','25'))))
API='https://api.clashroyale.com/v1'; NEWS='https://supercell.com/en/games/clashroyale/blog/'
state={'version':0,'running':False,'last_run':None,'error':None}; lock=threading.Lock()

def now(): return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
def con():
    c=sqlite3.connect(DB,timeout=20); c.row_factory=sqlite3.Row; c.execute('PRAGMA journal_mode=WAL'); return c

def init():
    c=con(); c.executescript('''
    CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY,name TEXT UNIQUE,icon_url TEXT,elixir INTEGER,rarity TEXT);
    CREATE TABLE IF NOT EXISTS meta_snapshots(id INTEGER PRIMARY KEY AUTOINCREMENT,snapshot_id TEXT,observed_at TEXT,mode TEXT,deck_key TEXT,deck_name TEXT,usage REAL,win_rate REAL,battles INTEGER,cards_json TEXT,source_note TEXT,UNIQUE(snapshot_id,deck_key));
    CREATE INDEX IF NOT EXISTS idx_meta_time ON meta_snapshots(observed_at DESC);
    CREATE INDEX IF NOT EXISTS idx_meta_deck ON meta_snapshots(deck_key,observed_at ASC);
    CREATE TABLE IF NOT EXISTS balance_changes(id INTEGER PRIMARY KEY AUTOINCREMENT,card_name TEXT,kind TEXT,field TEXT,before_value TEXT,after_value TEXT,percent_change REAL,patch_date TEXT,source_url TEXT,image_url TEXT,UNIQUE(card_name,field,patch_date,before_value,after_value));
    CREATE TABLE IF NOT EXISTS news_items(id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,url TEXT UNIQUE,discovered_at TEXT);
    CREATE TABLE IF NOT EXISTS cosmetics(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      category TEXT NOT NULL,
      name TEXT NOT NULL,
      release_date TEXT,
      acquisition_method TEXT,
      availability_status TEXT,
      limited INTEGER,
      ownership_rate REAL,
      asset_url TEXT,
      source_url TEXT,
      evidence_note TEXT,
      UNIQUE(category,name)
    );
    CREATE TABLE IF NOT EXISTS asset_sources(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE,
      url TEXT NOT NULL,
      source_type TEXT NOT NULL,
      last_sync_at TEXT,
      last_error TEXT,
      discovered_count INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS remote_assets(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      source_name TEXT NOT NULL,
      name TEXT NOT NULL,
      kind TEXT NOT NULL,
      url TEXT NOT NULL UNIQUE,
      discovered_at TEXT NOT NULL
    );
    ''')
    seed=[
    ('Hero Ice Wizard','nerf','Freeze Duration','7 sec','5 sec',-29,'2026-09-16'),('Goblinstein','nerf','Ability Duration','4 sec','3.5 sec',-13,'2026-09-16'),('Minion Giant','nerf','Damage','189','168',-11,'2026-09-16'),('Fire Spirit','buff','Damage','207','215',4,'2026-09-16')]
    src='https://supercell.com/en/games/clashroyale/blog/release-notes/september-balance-changes-2026/'
    for r in seed:c.execute('INSERT OR IGNORE INTO balance_changes(card_name,kind,field,before_value,after_value,percent_change,patch_date,source_url) VALUES(?,?,?,?,?,?,?,?)',(*r,src))
    for _n,_u,_t in [
        ('Supercell Fan Kit - Clash Royale','https://fankit.supercell.com/d/BmehSDJrZNff/game-assets-1','fankit'),
        ('Supercell Make - Emote Assets','https://make.supercell.com/en/create/clash-royale/emote/assets','make'),
        ('Supercell Make - Tower Skin Assets','https://make.supercell.com/en/create/clash-royale/tower-skin/assets','make')
    ]:
        c.execute('INSERT OR IGNORE INTO asset_sources(name,url,source_type) VALUES(?,?,?)',(_n,_u,_t))
    c.commit(); c.close()

def rows(sql,p=()):
    c=con(); out=[dict(x) for x in c.execute(sql,p).fetchall()]; c.close(); return out

def fetch(url,headers=None):
    h={'User-Agent':'CrownWatch/1.1'}; h.update(headers or {})
    with urlopen(Request(url,headers=h),timeout=20) as r:return r.read().decode('utf-8','replace')
def jfetch(url): return json.loads(fetch(url,{'Authorization':f'Bearer {TOKEN}','Accept':'application/json'}))

def collect_cards():
    if not TOKEN:return
    data=jfetch(f'{API}/cards'); c=con()
    for x in data.get('items',[]):
        c.execute('INSERT INTO cards(id,name,icon_url,elixir,rarity) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,icon_url=excluded.icon_url,elixir=excluded.elixir,rarity=excluded.rarity',(x.get('id'),x.get('name'),(x.get('iconUrls') or {}).get('medium'),x.get('elixirCost'),x.get('rarity')))
    c.commit(); c.close()

def collect_meta():
    if not TOKEN:return 0
    board=jfetch(f'{API}/locations/global/pathoflegend/players?limit={PLAYERS}').get('items',[])[:PLAYERS]
    stats=defaultdict(lambda:{'games':0,'wins':0.0,'cards':None}); seen=set()
    for p in board:
        try:battles=jfetch(f"{API}/players/{quote(p.get('tag',''),safe='')}/battlelog")
        except:continue
        if not isinstance(battles,list):continue
        for b in battles:
            if str(b.get('type','')).lower()!='pathoflegend':continue
            t=b.get('team') or []; o=b.get('opponent') or []
            if not t or not o:continue
            bid=(b.get('battleTime',''),)+tuple(sorted([t[0].get('tag',''),o[0].get('tag','')]))
            if bid in seen:continue
            seen.add(bid)
            tc=t[0].get('cards') or []; oc=o[0].get('cards') or []
            if len(tc)!=8 or len(oc)!=8:continue
            a,bcr=t[0].get('crowns',0),o[0].get('crowns',0)
            for cards,w in [(tc,1 if a>bcr else .5 if a==bcr else 0),(oc,1 if bcr>a else .5 if a==bcr else 0)]:
                k='-'.join(sorted(str(x.get('id','')) for x in cards)); stats[k]['games']+=1; stats[k]['wins']+=w; stats[k]['cards']=cards
    total=sum(v['games'] for v in stats.values())
    if not total:return 0
    observed=now(); sid=hashlib.sha1(observed.encode()).hexdigest()[:12]; c=con()
    for k,v in sorted(stats.items(),key=lambda kv:(kv[1]['games'],kv[1]['wins']),reverse=True)[:20]:
        cards=v['cards']; compact=[{'id':x.get('id'),'name':x.get('name'),'icon':(x.get('iconUrls') or {}).get('medium')} for x in cards]
        name=' • '.join(x.get('name','?') for x in cards[:4])+' +4'
        c.execute('INSERT OR IGNORE INTO meta_snapshots(snapshot_id,observed_at,mode,deck_key,deck_name,usage,win_rate,battles,cards_json,source_note) VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,observed,'top_ranked_sample',k,name,round(v['games']/total*100,2),round(v['wins']/v['games']*100,2),v['games'],json.dumps(compact,separators=(',',':')),f"Recent Ranked battle sample from {len(board)} top Path of Legend players."))
    c.commit(); c.close(); state['version']+=1; return len(stats)

def collect_news():
    try:html=fetch(NEWS)
    except:return
    links=re.findall(r'href=["\']([^"\']*/games/clashroyale/blog/release-notes/[^"\']+)["\']',html,re.I); c=con()
    for href in links[:20]:
        if href.startswith('/'):href='https://supercell.com'+href
        slug=href.rstrip('/').split('/')[-1]; title=' '.join(w.capitalize() for w in slug.replace('-',' ').split())
        c.execute('INSERT OR IGNORE INTO news_items(title,url,discovered_at) VALUES(?,?,?)',(title,href,now()))
    c.commit(); c.close()

def run_collect():
    with lock:
        if state['running']:return
        state['running']=True
    try:
        collect_news()
        if TOKEN: collect_cards(); collect_meta()
        state['last_run']=now(); state['error']=None
    except Exception as e:state['error']=str(e)
    finally:state['running']=False

def loop():
    while True:run_collect();time.sleep(POLL*60)

def times():return [x['observed_at'] for x in rows('SELECT DISTINCT observed_at FROM meta_snapshots ORDER BY observed_at DESC')]
def snap(t):
    d=rows('SELECT * FROM meta_snapshots WHERE observed_at=? ORDER BY battles DESC,win_rate DESC',(t,)) if t else []
    for x in d:x['cards']=json.loads(x.pop('cards_json'))
    return d

def latest_meta():
    ts=times(); cur=snap(ts[0]) if ts else []; old={x['deck_key']:x for x in snap(ts[1])} if len(ts)>1 else {}
    for x in cur:
        p=old.get(x['deck_key']); x['usage_delta']=round(x['usage']-p['usage'],2) if p else None; x['win_delta']=round(x['win_rate']-p['win_rate'],2) if p else None
    return cur

def watch_card(name):
    ts=times()
    def agg(t):
        found=[d for d in snap(t) if any((c.get('name') or '').lower()==name.lower() for c in d['cards'])]
        bt=sum(d['battles'] for d in found); wr=round(sum(d['win_rate']*d['battles'] for d in found)/bt,2) if bt else None
        return {'tracked_share':round(sum(d['usage'] for d in found),2),'weighted_win_rate':wr,'battles':bt,'deck_count':len(found)}
    cur=agg(ts[0]) if ts else {'tracked_share':0,'weighted_win_rate':None,'battles':0,'deck_count':0}; old=agg(ts[1]) if len(ts)>1 else None
    card=rows('SELECT * FROM cards WHERE lower(name)=lower(?) LIMIT 1',(name,)); patch=rows('SELECT * FROM balance_changes WHERE lower(card_name) LIKE lower(?) ORDER BY patch_date DESC,id DESC LIMIT 1',(f'%{name}%',))
    cur.update({'type':'card','key':name,'name':name,'icon_url':card[0].get('icon_url') if card else None,'elixir':card[0].get('elixir') if card else None,'rarity':card[0].get('rarity') if card else None,'latest_patch':patch[0] if patch else None,'share_delta':round(cur['tracked_share']-old['tracked_share'],2) if old else None})
    return cur

def watch_deck(key):
    ts=times(); cur=snap(ts[0]) if ts else []; old={x['deck_key']:x for x in snap(ts[1])} if len(ts)>1 else {}
    for i,d in enumerate(cur,1):
        if d['deck_key']==key:
            p=old.get(key); return {'type':'deck','key':key,'name':d['deck_name'],'rank':i,'usage':d['usage'],'win_rate':d['win_rate'],'battles':d['battles'],'cards':d['cards'],'usage_delta':round(d['usage']-p['usage'],2) if p else None}
    return {'type':'deck','key':key,'missing':True}

def card_detail(name):
    card=rows('SELECT * FROM cards WHERE lower(name)=lower(?) LIMIT 1',(name,)); changes=rows('SELECT * FROM balance_changes WHERE lower(card_name) LIKE lower(?) ORDER BY patch_date DESC,id DESC',(f'%{name}%',)); decks=[d for d in latest_meta() if any((c.get('name') or '').lower()==name.lower() for c in d['cards'])]
    return {'card':card[0] if card else None,'changes':changes,'decks':decks[:8]}

def player(tag):
    if not TOKEN:return {'error':'api_not_configured'}
    clean=tag.strip().replace(' ',''); clean=clean if clean.startswith('#') else '#'+clean
    try:p=jfetch(f'{API}/players/{quote(clean,safe="")}'); battles=jfetch(f'{API}/players/{quote(clean,safe="")}/battlelog')
    except Exception as e:return {'error':'lookup_failed','detail':str(e)}
    deck=[{'id':c.get('id'),'name':c.get('name'),'icon':(c.get('iconUrls') or {}).get('medium')} for c in p.get('currentDeck',[])]
    recent=[]
    for b in battles[:10] if isinstance(battles,list) else []:
        t=b.get('team') or []; o=b.get('opponent') or []
        if not t:continue
        me=t[0]; foe=o[0] if o else {}; a=me.get('crowns',0); z=foe.get('crowns',0)
        recent.append({'result':'win' if a>z else 'loss' if a<z else 'draw','crowns':a,'opponentCrowns':z,'opponent':foe.get('name','Unknown'),'cards':[{'id':c.get('id'),'name':c.get('name'),'icon':(c.get('iconUrls') or {}).get('medium')} for c in me.get('cards',[])]})
    return {'name':p.get('name'),'tag':p.get('tag'),'trophies':p.get('trophies'),'wins':p.get('wins'),'losses':p.get('losses'),'clan':(p.get('clan') or {}).get('name'),'currentDeck':deck,'recent':recent}



def _display_level(card):
    if not card:
        return None
    lvl=card.get('level')
    rarity=(card.get('rarity') or '').lower()
    if lvl is None:
        return None
    # Clash Royale API card levels are rarity-relative for non-common cards.
    offsets={
        'common':0,
        'rare':2,
        'epic':5,
        'legendary':8,
        'champion':10
    }
    # Tower Troops/support cards use the same rarity-relative convention.
    return int(lvl)+offsets.get(rarity,0)

def _recent_streak(battles):
    if not isinstance(battles,list) or not battles:
        return {'type':'none','count':0}
    count=0
    streak_type=None
    for b in battles:
        team=b.get('team') or []
        opp=b.get('opponent') or []
        if not team or not opp:
            continue
        me=team[0]; foe=opp[0]
        a=me.get('crowns',0); z=foe.get('crowns',0)
        result='win' if a>z else 'loss' if a<z else 'draw'
        if result=='draw':
            break
        if streak_type is None:
            streak_type=result
            count=1
        elif result==streak_type:
            count+=1
        else:
            break
    return {'type':streak_type or 'none','count':count}

def player_raw(tag):
    if not TOKEN:return {'error':'api_not_configured'}
    clean=tag.strip().replace(' ',''); clean=clean if clean.startswith('#') else '#'+clean
    try:
        p=jfetch(f'{API}/players/{quote(clean,safe="")}')
        battles=jfetch(f'{API}/players/{quote(clean,safe="")}/battlelog')
    except Exception as e:
        return {'error':'lookup_failed','detail':str(e)}
    return {
        'tag':p.get('tag'),'name':p.get('name'),
        'top_level_fields':sorted(p.keys()),
        'payload':p,
        'computedStreak':_recent_streak(battles)
    }

def cosmetics(q='',category='all'):
    sql='SELECT * FROM cosmetics'
    args=[]; clauses=[]
    if category!='all':
        clauses.append('category=?'); args.append(category)
    if q.strip():
        clauses.append('lower(name) LIKE lower(?)'); args.append('%'+q.strip()+'%')
    if clauses: sql+=' WHERE '+' AND '.join(clauses)
    sql+=' ORDER BY category,name'
    return rows(sql,args)

def cosmetic_summary(x):
    # factual labels only; ownership_rate remains nullable unless sourced
    flags=[]
    if x.get('availability_status'): flags.append(x['availability_status'])
    if x.get('limited'): flags.append('Limited')
    if x.get('ownership_rate') is not None: flags.append(f"{x['ownership_rate']}% ownership")
    return flags

def _kind_from_url(u):
    ext=u.lower().split('?')[0].rsplit('.',1)[-1] if '.' in u.split('?')[0] else ''
    if ext in ('png','jpg','jpeg','webp','gif','svg'): return 'image'
    if ext in ('mp3','wav','ogg','m4a'): return 'audio'
    if ext in ('mp4','webm','mov'): return 'video'
    if ext in ('zip','rar','7z'): return 'archive'
    return 'link'

def sync_asset_sources():
    sources=rows('SELECT * FROM asset_sources ORDER BY id')
    total_new=0; results=[]
    for s in sources:
        found=[]
        err=None
        try:
            html=fetch(s['url'])
            # Pull direct downloadable/media links exposed in public HTML.
            hrefs=re.findall(r"""(?:href|src)=["']([^"']+)["']""", html, re.I)
            for u in hrefs:
                if u.startswith('//'):u='https:'+u
                elif u.startswith('/'):
                    base='/'.join(s['url'].split('/')[:3]); u=base+u
                if not u.startswith('http'):continue
                kind=_kind_from_url(u)
                if kind=='link' and not any(k in u.lower() for k in ('download','asset','media','cdn','inbox.supercell')):continue
                name=u.split('?')[0].rstrip('/').split('/')[-1] or 'asset'
                found.append((name,kind,u))
            # dedupe
            uniq={u:(n,k,u) for n,k,u in found}
            found=list(uniq.values())
            c=con(); before=c.total_changes
            for n,k,u in found:
                c.execute('INSERT OR IGNORE INTO remote_assets(source_name,name,kind,url,discovered_at) VALUES(?,?,?,?,?)',(s['name'],n,k,u,now()))
            c.execute('UPDATE asset_sources SET last_sync_at=?,last_error=NULL,discovered_count=? WHERE id=?',(now(),len(found),s['id']))
            c.commit(); added=c.total_changes-before-1; c.close()
            total_new+=max(0,added)
        except Exception as e:
            err=str(e)[:250]
            c=con(); c.execute('UPDATE asset_sources SET last_sync_at=?,last_error=? WHERE id=?',(now(),err,s['id'])); c.commit(); c.close()
        results.append({'name':s['name'],'found':len(found),'error':err})
    return {'new':total_new,'sources':results}

def remote_assets(q='',kind='all'):
    sql='SELECT * FROM remote_assets'; args=[]; clauses=[]
    if kind!='all': clauses.append('kind=?'); args.append(kind)
    if q.strip():
        clauses.append('(lower(name) LIKE lower(?) OR lower(source_name) LIKE lower(?))')
        args.extend(['%'+q.strip()+'%']*2)
    if clauses: sql+=' WHERE '+' AND '.join(clauses)
    sql+=' ORDER BY id DESC LIMIT 500'
    return rows(sql,args)

def asset_source_status():
    return rows('SELECT * FROM asset_sources ORDER BY id')

def assets(q='',kind='all'):
    p=STATIC/'asset-catalog.json'
    if not p.exists():return []
    try:d=json.loads(p.read_text())
    except:return []
    q=q.lower().strip(); out=[]
    for a in d:
        if kind!='all' and a.get('kind')!=kind:continue
        if q and q not in (' '.join(str(a.get(k,'')) for k in ('name','filename','folder','kind'))).lower():continue
        out.append(a)
    return out[:500]

class H(SimpleHTTPRequestHandler):
    def translate_path(self,path):
        p=urlparse(path).path; p='/index.html' if p=='/' else p; return str(STATIC/p.lstrip('/'))
    def log_message(self,fmt,*args):
        if args and str(args[1]).startswith(('4','5')):super().log_message(fmt,*args)
    def out(self,d):
        b=json.dumps(d).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p=urlparse(self.path); q=parse_qs(p.query)
        if p.path=='/favicon.ico':self.send_response(204);self.end_headers();return
        if p.path=='/api/status':return self.out({'token_configured':bool(TOKEN),'poll_minutes':POLL,'snapshot_count':len(times()),'meta_updated':times()[0] if times() else None,'collector_running':state['running'],'error':state['error']})
        if p.path=='/api/meta':return self.out(latest_meta())
        if p.path=='/api/card':return self.out(card_detail(q.get('name',[''])[0]))
        if p.path=='/api/watch/card':return self.out(watch_card(q.get('name',[''])[0]))
        if p.path=='/api/watch/deck':return self.out(watch_deck(q.get('key',[''])[0]))
        if p.path=='/api/player':return self.out(player(q.get('tag',[''])[0]))
        if p.path=='/api/player/raw':return self.out(player_raw(q.get('tag',[''])[0]))
        if p.path=='/api/cosmetics':return self.out(cosmetics(q.get('q',[''])[0],q.get('category',['all'])[0]))
        if p.path=='/api/assets':return self.out(assets(q.get('q',[''])[0],q.get('kind',['all'])[0]))
        if p.path=='/api/remote-assets':return self.out(remote_assets(q.get('q',[''])[0],q.get('kind',['all'])[0]))
        if p.path=='/api/asset-sources':return self.out(asset_source_status())
        if p.path=='/api/asset-sync':
            threading.Thread(target=sync_asset_sources,daemon=True).start()
            return self.out({'started':True})
        if p.path=='/api/refresh':threading.Thread(target=run_collect,daemon=True).start();return self.out({'started':True})
        return super().do_GET()

if __name__=='__main__':
    init(); threading.Thread(target=loop,daemon=True).start(); print(f'CrownWatch V1.1 -> http://127.0.0.1:{PORT}')
    try:ThreadingHTTPServer(('127.0.0.1',PORT),H).serve_forever()
    except KeyboardInterrupt:print('\nCrownWatch shutting down cleanly.')
