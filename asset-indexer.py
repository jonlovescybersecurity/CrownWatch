from pathlib import Path
import shutil, json, sys, hashlib
ROOT=Path(__file__).parent; DEST=ROOT/'static'/'catalog'; CAT=ROOT/'static'/'asset-catalog.json'
KINDS={'.png':'image','.jpg':'image','.jpeg':'image','.webp':'image','.gif':'image','.mp3':'audio','.wav':'audio','.ogg':'audio','.m4a':'audio','.mp4':'video','.webm':'video','.mov':'video'}
if len(sys.argv)<2:
    raise SystemExit('Usage: python asset-indexer.py "C:\\path\\to\\downloaded\\fan-kit-assets"')
src=Path(sys.argv[1]).expanduser().resolve()
if not src.is_dir():raise SystemExit(f'Folder not found: {src}')
DEST.mkdir(parents=True,exist_ok=True); out=[]
for p in src.rglob('*'):
    if not p.is_file() or p.suffix.lower() not in KINDS:continue
    name=hashlib.sha1(str(p).encode()).hexdigest()[:10]+'_'+p.name; dest=DEST/name
    if not dest.exists() or dest.stat().st_size!=p.stat().st_size:shutil.copy2(p,dest)
    out.append({'name':p.stem.replace('_',' ').replace('-',' '),'filename':p.name,'folder':str(p.parent.relative_to(src)) if p.parent!=src else '','kind':KINDS[p.suffix.lower()],'url':'/catalog/'+name})
out.sort(key=lambda x:(x['kind'],x['name'].lower())); CAT.write_text(json.dumps(out,indent=2),encoding='utf-8')
print(f'Indexed {len(out)} assets. Refresh CrownWatch and open Asset Lab.')
