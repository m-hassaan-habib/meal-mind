from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
from datetime import date, timedelta, datetime
import csv, io, random
import config
from db import close_db, query, execute
import os, uuid
from PIL import Image
import re
from difflib import get_close_matches
import requests



UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.teardown_appcontext(close_db)


def _name_key(s):
    return re.sub(r'\s+', ' ', (s or '').strip().lower())

def combine_override_results(raw, lib, web):
    toks = set(ingredient_terms_from_text(raw))
    for r in lib:
        r['source'] = 'library'
        r['score'] = r.get('score', 1)
    for w in web:
        w['source'] = 'web'
        name_tokens = set(re.findall(r'[a-z]+', (w.get('name') or '').lower()))
        overlap = len(toks & name_tokens)
        area = (w.get('cuisine') or '').lower()
        bias = 1 if area in ('pakistani','indian','bangladeshi','afghan') else 0
        w['score'] = w.get('score', 1) + overlap + bias
    merged = lib + web
    out, seen = [], set()
    for m in merged:
        k = _name_key(m.get('name'))
        if k in seen:
            continue
        seen.add(k)
        out.append(m)
    out.sort(key=lambda x: (-x.get('score',0), 0 if x.get('source')=='library' else 1, x.get('time_min') or 999, x.get('name') or ''))
    return out


def web_find_recipes(raw):
    q = raw.replace('+',' ').replace('|',' ').replace('-',' ').strip()
    out = []
    try:
        r = requests.get('https://www.themealdb.com/api/json/v1/1/search.php', params={'s': q}, timeout=6)
        j = r.json() if r.status_code==200 else {}
        meals = j.get('meals') or []
        for m in meals:
            area = (m.get('strArea') or '')
            if area not in ['Pakistani','Indian','Bangladeshi','Afghan','Middle Eastern','Arabic','Unknown']:
                continue
            out.append({
                'id': int(m.get('idMeal')),
                'name': m.get('strMeal'),
                'cuisine': area or '—',
                'time_min': 40,
                'difficulty': 'Medium',
                'veg': 0,
                'spice_level': 'Medium',
                'image_url': m.get('strMealThumb'),
                'external': True,
                'source_url': m.get('strSource') or f"https://www.themealdb.com/meal/{m.get('idMeal')}"
            })
        if not out:
            toks = [t for t in re.split(r'[\s\+\|\-]+', q.lower()) if t]
            best = toks[0] if toks else 'dal'
            r = requests.get('https://www.themealdb.com/api/json/v1/1/search.php', params={'s': best}, timeout=6)
            j = r.json() if r.status_code==200 else {}
            meals = j.get('meals') or []
            for m in meals[:8]:
                area = (m.get('strArea') or '')
                out.append({
                    'id': int(m.get('idMeal')),
                    'name': m.get('strMeal'),
                    'cuisine': area or '—',
                    'time_min': 40,
                    'difficulty': 'Medium',
                    'veg': 0,
                    'spice_level': 'Medium',
                    'image_url': m.get('strMealThumb'),
                    'external': True,
                    'source_url': m.get('strSource') or f"https://www.themealdb.com/meal/{m.get('idMeal')}"
                })
    except Exception:
        return []
    names = set()
    dedup = []
    for r in out:
        if r['name'] in names: continue
        names.add(r['name']); dedup.append(r)
    return dedup[:10]


def resolve_ingredient_ids(tokens):
    if not tokens:
        return {}
    names = [t for t in tokens]
    rows = query('SELECT id,name FROM ingredients WHERE name IN ('+','.join(['%s']*len(names))+')', names)
    known = {r['name']: r['id'] for r in rows}
    if len(known) == len(tokens):
        return {t: known[t] for t in tokens}
    all_names = [r['name'] for r in query('SELECT name FROM ingredients')]
    resolved = {}
    for t in tokens:
        if t in known:
            resolved[t] = known[t]
            continue
        cand = get_close_matches(t, all_names, n=1, cutoff=0.8)
        if cand:
            rid = query('SELECT id FROM ingredients WHERE name=%s', (cand[0],), one=True)['id']
            resolved[t] = rid
    return resolved

def dish_name_hits(raw):
    raw = raw.strip()
    if not raw:
        return []
    rows = list(query(
        'SELECT id,name,cuisine,time_min,difficulty,veg,spice_level,image_url '
        'FROM dishes WHERE name LIKE %s '
        'ORDER BY CASE WHEN name=%s THEN 0 ELSE 1 END, LENGTH(name) ASC LIMIT 5',
        (f'%{raw}%', raw)
    ))
    for r in rows:
        r['score'] = 999
        r['hit_labels'] = ['name match']
    return rows



def _center_crop_ratio(img, rw=16, rh=9):
    w, h = img.size
    tr = rw / rh
    cr = w / h
    if cr > tr:
        nw = int(h * tr)
        x = (w - nw) // 2
        return img.crop((x, 0, x + nw, h))
    nh = int(w / tr)
    y = (h - nh) // 2
    return img.crop((0, y, w, y + nh))


def save_image(fileobj, w=1280, h=720):
    img = Image.open(fileobj.stream)
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
    img = _center_crop_ratio(img, 16, 9).resize((w, h), Image.LANCZOS)
    name = f"{uuid.uuid4().hex}.webp"
    path = os.path.join(UPLOAD_DIR, name)
    img.save(path, format='WEBP', quality=85, method=6)
    return f"/static/uploads/{name}"


@app.context_processor
def url_helpers():
    def url_for_history(**kwargs):
        args = dict(request.args)
        args.update(kwargs)
        return url_for('history', **args)
    return dict(url_for_history=url_for_history)

def get_prefs(user_id=1):
    row = query('SELECT * FROM preferences WHERE user_id=%s', (user_id,), one=True)
    if not row:
        execute('INSERT INTO preferences (user_id) VALUES (%s)', (user_id,))
        row = query('SELECT * FROM preferences WHERE user_id=%s', (user_id,), one=True)
    return row

def get_cooldown_days(user_id=1):
    prefs = get_prefs(user_id)
    d = prefs.get('cooldown_days') or config.COOLDOWN_DAYS
    return int(d)

def pick_candidate(user_id=1):
    today = date.today()
    cd = get_cooldown_days(user_id)
    pf_sql, pf_params = pref_filter_sql(user_id)
    params = [user_id, user_id, today - timedelta(days=cd)] + pf_params
    rows = query('SELECT d.*, ul.last_cooked_at FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1 AND d.id NOT IN (SELECT dish_id FROM day_plan WHERE user_id=%s AND date >= %s)' + pf_sql, params)
    if not rows:
        params = [user_id] + pf_params
        rows = query('SELECT d.*, ul.last_cooked_at FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1' + pf_sql, params)
    if not rows:
        return None
    def score(r):
        lc = r.get('last_cooked_at')
        base = 0 if lc is None else (today - lc).days
        return base + random.random()
    rows.sort(key=score, reverse=True)
    return rows[0]


def get_or_create_today_plan(user_id=1):
    today_d = date.today()
    existing = query('SELECT d.*, dp.is_override FROM day_plan dp JOIN dishes d ON d.id=dp.dish_id WHERE dp.user_id=%s AND dp.date=%s', (user_id, today_d), one=True)
    if existing:
        return existing
    prefs = get_prefs(user_id)
    if prefs.get('auto_suggestions', 1):
        cand = pick_candidate(user_id)
        if cand:
            execute('INSERT INTO day_plan (user_id,date,dish_id,is_override) VALUES (%s,%s,%s,0) ON DUPLICATE KEY UPDATE dish_id=VALUES(dish_id), is_override=0', (user_id, today_d, cand['id']))
            return query('SELECT d.*, dp.is_override FROM day_plan dp JOIN dishes d ON d.id=dp.dish_id WHERE dp.user_id=%s AND dp.date=%s', (user_id, today_d), one=True)
    return pick_candidate(user_id)

def alt_picks(exclude_id, user_id=1, limit=3):
    today = date.today()
    cd = get_cooldown_days(user_id)
    pf_sql, pf_params = pref_filter_sql(user_id)
    params = [user_id, exclude_id, user_id, today - timedelta(days=cd)] + pf_params
    rows = query('SELECT d.*, ul.last_cooked_at FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1 AND d.id<>%s AND d.id NOT IN (SELECT dish_id FROM day_plan WHERE user_id=%s AND date>=%s)' + pf_sql, params)
    if not rows:
        params = [user_id, exclude_id] + pf_params
        rows = query('SELECT d.*, ul.last_cooked_at FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1 AND d.id<>%s' + pf_sql, params)
    random.shuffle(rows)
    return rows[:limit]


def days_ago(d):
    if not d:
        return None
    return (date.today() - d).days

@app.route('/')
def today():
    pick = get_or_create_today_plan(1)
    alts = alt_picks(pick['id'], 1, 3) if pick else []
    recent = query('SELECT d.*, dp.date AS cooked_date FROM day_plan dp JOIN dishes d ON d.id=dp.dish_id WHERE dp.user_id=%s ORDER BY dp.date DESC LIMIT 6', (1,))
    cooldown = get_cooldown_days(1)
    return render_template('today.html', pick=pick, alts=alts, recent=recent, days_ago=days_ago, cooldown=cooldown, rotate_seconds=config.DEV_ROTATE_SECONDS)

@app.get('/api/pick')
def api_pick():
    force = request.args.get('force')
    p = pick_candidate(1) if force else get_or_create_today_plan(1)
    if not p:
        return jsonify({}), 404
    x = dict(p)
    v = x.get('last_cooked_at')
    if isinstance(v, (date, datetime)):
        x['last_cooked_at'] = v.isoformat()
    return jsonify(x)

@app.post('/cook')
def cook():
    dish_id = int(request.form['dish_id'])
    today_d = date.today()
    exist = query('SELECT id FROM day_plan WHERE user_id=%s AND date=%s', (1, today_d), one=True)
    if not exist:
        execute('INSERT INTO day_plan (user_id,date,dish_id,is_override) VALUES (%s,%s,%s,0)', (1, today_d, dish_id))
    else:
        execute('UPDATE day_plan SET dish_id=%s,is_override=0 WHERE id=%s', (dish_id, exist['id']))
    execute('UPDATE user_library SET last_cooked_at=%s WHERE user_id=%s AND dish_id=%s', (today_d, 1, dish_id))
    return redirect(url_for('today'))

@app.post('/swap')
def swap():
    dish_id = int(request.form['dish_id'])
    alts = alt_picks(dish_id, 1, 3)
    return jsonify(alts)

@app.get('/override')
def override_get():
    return render_template('override.html')


def normalize_tokens(s):
    s = s.lower().strip()
    s = s.replace(',', ' ')
    s = s.replace('/', ' | ')
    s = re.sub(r'\band\b', '+', s)
    s = re.sub(r'\bor\b', '|', s)
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'([+\-|])', r' \1 ', s).strip()
    parts = [p for p in s.split() if p]
    op = '+'
    required, optional, excluded = [], [], []
    for p in parts:
        if p in ['+','|','-']:
            op = p
            continue
        if p.endswith('s') and len(p) > 3:
            p = p[:-1]
        aliases = {
            'chkn':'chicken','chikn':'chicken','chk':'chicken','murghi':'chicken',
            'qeema':'keema','keema':'keema',
            'aloo':'potato','bhindi':'okra','saag':'spinach','machli':'fish',
            'dal':'dal','daal':'dal','dāl':'dal',
            'masoor':'masoor dal','moong':'moong dal','chanadal':'chana dal','chana':'chana dal','mash':'urad dal','urad':'urad dal',
            'chawal':'rice','chāwal':'rice'
        }

        p = aliases.get(p, p)
        if op == '-':
            excluded.append(p)
        elif op == '|':
            optional.append(p)
        else:
            required.append(p)
    return required, optional, excluded


def resolve_ingredient_ids(tokens):
    if not tokens:
        return {}
    names = [t for t in tokens]
    rows = query('SELECT id,name FROM ingredients WHERE name IN ('+','.join(['%s']*len(names))+')', names)
    known = {r['name']: r['id'] for r in rows}
    if len(known) == len(tokens):
        return {t: known[t] for t in tokens}
    all_names = [r['name'] for r in query('SELECT name FROM ingredients')]
    resolved = {}
    for t in tokens:
        if t in known:
            resolved[t] = known[t]
            continue
        cand = get_close_matches(t, all_names, n=1, cutoff=0.8)
        if cand:
            rid = query('SELECT id FROM ingredients WHERE name=%s', (cand[0],), one=True)['id']
            resolved[t] = rid
    return resolved


def dish_name_hits(raw):
    raw = raw.strip()
    if not raw:
        return []
    rows = query('SELECT id,name,cuisine,time_min,difficulty,veg,spice_level,image_url FROM dishes WHERE name LIKE %s ORDER BY CASE WHEN name=%s THEN 0 ELSE 1 END, LENGTH(name) ASC LIMIT 5', (f'%{raw}%', raw))
    for r in rows:
        r['score'] = 999
        r['hit_labels'] = ['name match']
    return rows


def match_dishes(raw):
    req, opt, ex = normalize_tokens(raw)
    rid = resolve_ingredient_ids(req)
    oid = resolve_ingredient_ids(opt)
    xid = resolve_ingredient_ids(ex)
    req_ids = set(rid.values())
    opt_ids = set(oid.values())
    ex_ids = set(xid.values())
    all_ids = list(req_ids | opt_ids | ex_ids)

    hits = list(dish_name_hits(raw))  # force list

    if not all_ids:
        return hits

    placeholders = ','.join(['%s']*len(all_ids))
    rows = query(f'''
        SELECT d.id,d.name,d.cuisine,d.time_min,d.difficulty,d.veg,d.spice_level,d.image_url,
               GROUP_CONCAT(i.id) AS hit_ids,
               GROUP_CONCAT(i.name) AS hit_names
        FROM dishes d
        JOIN dish_ingredients di ON di.dish_id=d.id
        JOIN ingredients i ON i.id=di.ingredient_id
        WHERE di.ingredient_id IN ({placeholders})
        GROUP BY d.id
    ''', all_ids)

    out, seen = [], set()
    for r in rows:
        ids = set(map(int, r['hit_ids'].split(','))) if r['hit_ids'] else set()
        if ex_ids & ids:
            continue
        if req_ids and not req_ids.issubset(ids):
            continue
        score = len(req_ids & ids)*2 + len(opt_ids & ids)
        if score <= 0:
            continue
        r['score'] = score
        r['hit_labels'] = [n for n in (r['hit_names'] or '').split(',') if n]
        if r['id'] not in seen:
            out.append(r); seen.add(r['id'])

    out.sort(key=lambda x: (-x['score'], x.get('time_min') or 999, x['name']))
    id_hits = {h['id'] for h in hits}
    return hits + [o for o in out if o['id'] not in id_hits]


def ensure_ing(name):
    r = query('SELECT id FROM ingredients WHERE name=%s', (name,), one=True)
    return r['id'] if r else execute('INSERT INTO ingredients (name) VALUES (%s)', (name,))

def ensure_dish(d):
    r = query('SELECT id FROM dishes WHERE name=%s', (d['name'],), one=True)
    if r:
        return r['id']
    return execute('INSERT INTO dishes (name,cuisine,time_min,difficulty,veg,spice_level,image_url) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                   (d['name'], d['cuisine'], d['time_min'], d['difficulty'], d['veg'], d['spice_level'], d.get('image_url','/static/img/placeholder.jpg')))

def link_di(dish_id, ing_names):
    for n in ing_names:
        iid = ensure_ing(n)
        execute('INSERT IGNORE INTO dish_ingredients (dish_id,ingredient_id) VALUES (%s,%s)', (dish_id, iid))

@app.post('/admin/seed_pk_basics')
def seed_pk_basics():
    catalog = [
        {'name':'Dal Chawal','cuisine':'Pakistani','time_min':35,'difficulty':'Easy','veg':1,'spice_level':'Medium','ings':['rice','dal','onion','tomato','garlic','ginger','cumin','turmeric','red chili','salt','oil']},
        {'name':'Khichdi','cuisine':'Pakistani','time_min':30,'difficulty':'Easy','veg':1,'spice_level':'Low','ings':['rice','moong dal','onion','ginger','cumin','turmeric','salt','ghee']},
        {'name':'Moong Dal Khichdi','cuisine':'Pakistani','time_min':30,'difficulty':'Easy','veg':1,'spice_level':'Low','ings':['rice','moong dal','cumin','turmeric','salt','ghee']},
        {'name':'Masoor Dal with Rice','cuisine':'Pakistani','time_min':35,'difficulty':'Easy','veg':1,'spice_level':'Medium','ings':['rice','masoor dal','onion','tomato','garlic','ginger','cumin','turmeric','red chili','salt','oil']},
        {'name':'Chana Dal Fry + Rice','cuisine':'Pakistani','time_min':40,'difficulty':'Medium','veg':1,'spice_level':'Medium','ings':['rice','chana dal','onion','tomato','garlic','ginger','cumin','turmeric','red chili','salt','oil']},
        {'name':'Tarka Dal & Zeera Rice','cuisine':'Pakistani','time_min':40,'difficulty':'Medium','veg':1,'spice_level':'Medium','ings':['rice','dal','onion','garlic','ginger','cumin','green chili','ghee','salt']},
        {'name':'Urad Dal Mash + Rice','cuisine':'Pakistani','time_min':45,'difficulty':'Medium','veg':1,'spice_level':'Medium','ings':['rice','urad dal','onion','tomato','garlic','ginger','cumin','red chili','salt','oil']}
    ]
    for d in catalog:
        did = ensure_dish(d)
        link_di(did, d['ings'])
        execute('INSERT IGNORE INTO user_library (user_id,dish_id) VALUES (%s,%s)', (1, did))
    return redirect(url_for('library'))



@app.post('/override')
def override_post():
    raw = request.form.get('ingredients','').strip()
    lib = match_dishes(raw)
    web = web_find_recipes(raw)
    items = combine_override_results(raw, lib, web)
    return render_template('override_results.html', raw=raw, items=items, lib_count=len(lib), web_count=len(web))



@app.post('/override/add')
def override_add():
    dish_id = int(request.form['dish_id'])
    execute('INSERT IGNORE INTO user_library (user_id,dish_id) VALUES (%s,%s)', (1,dish_id))
    return redirect(url_for('library'))


@app.post('/override/confirm')
def override_confirm():
    dish_id = int(request.form['dish_id'])
    today_d = date.today()
    exist = query('SELECT id FROM day_plan WHERE user_id=%s AND date=%s', (1, today_d), one=True)
    if not exist:
        execute('INSERT INTO day_plan (user_id,date,dish_id,is_override) VALUES (%s,%s,%s,1)', (1, today_d, dish_id))
    else:
        execute('UPDATE day_plan SET dish_id=%s,is_override=1 WHERE id=%s', (dish_id, exist['id']))
    execute('UPDATE user_library SET last_cooked_at=%s WHERE user_id=%s AND dish_id=%s', (today_d, 1, dish_id))
    return redirect(url_for('today'))

@app.get('/library')
def library():
    q = request.args.get('q','').strip()
    if q:
        rows = query('SELECT d.*, ul.last_cooked_at FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1 AND d.name LIKE %s ORDER BY d.name ASC', (1, f'%{q}%'))
    else:
        rows = query('SELECT d.*, ul.last_cooked_at FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1 ORDER BY d.name ASC', (1,))
    return render_template('library.html', rows=rows, q=q, days_ago=days_ago)

@app.post('/library/add')
def library_add():
    name = request.form.get('name','').strip()
    ingredients = request.form.get('ingredients','').strip()
    time_min = int(request.form.get('time_min','30') or 30)
    veg = int(request.form.get('veg','0') or 0)
    difficulty = request.form.get('difficulty','Easy')
    cuisine = request.form.get('cuisine','')
    spice = request.form.get('spice_level','Medium')
    img_url_text = request.form.get('image_url','').strip()
    img_file = request.files.get('image')
    if img_file and img_file.filename:
        img = save_image(img_file)
    elif img_url_text:
        img = img_url_text
    else:
        img = '/static/img/placeholder.jpg'
    row = query('SELECT id FROM dishes WHERE name=%s', (name,), one=True)
    if not row:
        dish_id = execute('INSERT INTO dishes (name,cuisine,time_min,difficulty,veg,spice_level,image_url) VALUES (%s,%s,%s,%s,%s,%s,%s)', (name,cuisine,time_min,difficulty,veg,spice,img))
    else:
        dish_id = row['id']
        execute('UPDATE dishes SET image_url=%s WHERE id=%s', (img, dish_id))
    execute('INSERT IGNORE INTO user_library (user_id,dish_id) VALUES (%s,%s)', (1,dish_id))
    toks = ingredient_terms_from_text(ingredients)
    for t in toks:
        ing = query('SELECT id FROM ingredients WHERE name=%s', (t,), one=True)
        iid = ing['id'] if ing else execute('INSERT INTO ingredients (name) VALUES (%s)', (t,))
        execute('INSERT IGNORE INTO dish_ingredients (dish_id,ingredient_id) VALUES (%s,%s)', (dish_id,iid))
    return redirect(url_for('library'))


@app.get('/history')
def history():
    q = request.args.get('q', '').strip()
    period = request.args.get('period', 'all')
    typ = request.args.get('type', 'all')
    page = max(int(request.args.get('page', 1) or 1), 1)
    per = min(max(int(request.args.get('per', 10) or 10), 5), 50)

    where = ['dp.user_id=%s']
    params = [1]
    today = date.today()

    if period != 'all':
        if period == 'today':
            start, end = today, today
        elif period == 'yesterday':
            d = today - timedelta(days=1)
            start, end = d, d
        elif period in ['7d', 'week']:
            start, end = today - timedelta(days=7), today
        elif period in ['15d']:
            start, end = today - timedelta(days=15), today
        elif period in ['30d', 'month']:
            start, end = today - timedelta(days=30), today
        elif period in ['365d', 'year']:
            start, end = today - timedelta(days=365), today
        else:
            start, end = None, None
        if start:
            where.append('dp.date BETWEEN %s AND %s')
            params.extend([start, end])

    if q:
        where.append('d.name LIKE %s')
        params.append(f'%{q}%')

    if typ == 'override':
        where.append('dp.is_override=1')
    elif typ == 'cooked':
        where.append('dp.is_override=0')

    base = ' FROM day_plan dp JOIN dishes d ON d.id=dp.dish_id WHERE ' + ' AND '.join(where)
    total = query('SELECT COUNT(*) c' + base, params, one=True)['c']
    rows = query('SELECT d.*, dp.date AS cooked_date, dp.is_override' + base + ' ORDER BY dp.date DESC, dp.id DESC LIMIT %s OFFSET %s', params + [per, (page - 1) * per])
    pages = max((total + per - 1) // per, 1)

    return render_template('history.html', rows=rows, q=q, period=period, typ=typ, page=page, pages=pages, per=per, total=total)


@app.get('/discover')
def discover():
    pf_sql, pf_params = pref_filter_sql(1)
    picks = query('SELECT id,name,cuisine,time_min,difficulty,veg,spice_level,image_url FROM dishes d WHERE 1=1' + pf_sql + ' ORDER BY RAND() LIMIT 6', pf_params)
    return render_template('discover.html', picks=picks)


@app.post('/discover/add')
def discover_add():
    dish_id = int(request.form['dish_id'])
    execute('INSERT IGNORE INTO user_library (user_id,dish_id) VALUES (%s,%s)', (1,dish_id))
    return redirect(url_for('library'))

@app.get('/settings')
def settings():
    prefs = get_prefs(1)
    stats = {}
    stats['total'] = query('SELECT COUNT(*) c FROM user_library WHERE user_id=%s AND active=1', (1,), one=True)['c']
    stats['cuisines'] = query('SELECT COUNT(DISTINCT d.cuisine) c FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1 AND COALESCE(d.cuisine,"")<>""', (1,), one=True)['c']
    avg = query('SELECT ROUND(AVG(d.time_min)) a FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1', (1,), one=True)['a']
    stats['avg_time'] = avg or 0
    vegp = query('SELECT ROUND(AVG(d.veg)*100) p FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1', (1,), one=True)['p']
    stats['veg_pct'] = vegp or 0
    return render_template('settings.html', prefs=prefs, stats=stats)

@app.post('/settings')
def settings_save():
    diet = request.form.get('diet','None')
    spice = request.form.get('spice_level','Medium')
    time_max = int(request.form.get('time_max','60') or 60)
    notify = request.form.get('notify_time','19:00')
    daily = 1 if request.form.get('daily_suggestions') else 0
    weekly = 1 if request.form.get('weekly_discovery') else 0
    auto = 1 if request.form.get('auto_suggestions') else 0
    cooldown_days = int(request.form.get('cooldown_days','4') or 4)
    allergies = request.form.get('allergies','')
    avoid = request.form.get('avoid','')
    theme = request.form.get('theme','light')
    execute('INSERT INTO preferences (user_id,diet,spice_level,time_max,notify_time,daily_suggestions,weekly_discovery,auto_suggestions,cooldown_days,allergies,avoid,theme) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE diet=VALUES(diet),spice_level=VALUES(spice_level),time_max=VALUES(time_max),notify_time=VALUES(notify_time),daily_suggestions=VALUES(daily_suggestions),weekly_discovery=VALUES(weekly_discovery),auto_suggestions=VALUES(auto_suggestions),cooldown_days=VALUES(cooldown_days),allergies=VALUES(allergies),avoid=VALUES(avoid),theme=VALUES(theme)', (1,diet,spice,time_max,notify,daily,weekly,auto,cooldown_days,allergies,avoid,theme))
    return redirect(url_for('settings'))

@app.get('/settings/export')
def export_library():
    rows = query('SELECT d.name,d.cuisine,d.time_min,difficulty,veg,spice_level FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1 ORDER BY d.name', (1,))
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['name','cuisine','time_min','difficulty','veg','spice_level'])
    for r in rows:
        w.writerow([r['name'], r['cuisine'] or '', r['time_min'] or '', r['difficulty'] or '', r['veg'] or 0, r['spice_level'] or ''])
    csv_data = output.getvalue()
    return Response(csv_data, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=library.csv'})

@app.post('/settings/import')
def import_library():
    f = request.files.get('file')
    if not f:
        return redirect(url_for('settings'))
    text = f.read().decode('utf-8', errors='ignore')
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        name = (row.get('name') or '').strip()
        if not name:
            continue
        cuisine = (row.get('cuisine') or '').strip()
        time_min = int((row.get('time_min') or 30))
        difficulty = (row.get('difficulty') or 'Easy').strip()
        veg = 1 if str(row.get('veg') or '0') in ['1','true','True','yes','Yes'] else 0
        spice = (row.get('spice_level') or 'Medium').strip()
        img = '/static/img/placeholder.jpg'
        d = query('SELECT id FROM dishes WHERE name=%s', (name,), one=True)
        if not d:
            dish_id = execute('INSERT INTO dishes (name,cuisine,time_min,difficulty,veg,spice_level,image_url) VALUES (%s,%s,%s,%s,%s,%s,%s)', (name,cuisine,time_min,difficulty,veg,spice,img))
        else:
            dish_id = d['id']
        execute('INSERT IGNORE INTO user_library (user_id,dish_id) VALUES (%s,%s)', (1,dish_id))
    return redirect(url_for('settings'))


@app.post('/dish/<int:dish_id>/image')
def dish_image(dish_id):
    img_file = request.files.get('image')
    img_url_text = request.form.get('image_url','').strip()
    if img_file and img_file.filename:
        url = save_image(img_file)
    elif img_url_text:
        url = img_url_text
    else:
        return redirect(url_for('library'))
    execute('UPDATE dishes SET image_url=%s WHERE id=%s', (url, dish_id))
    return redirect(url_for('library'))


def pref_filter_sql(user_id=1):
    p = get_prefs(user_id)
    w, params = [], []

    tm = p.get('time_max')
    if tm:
        w.append('d.time_min<=%s'); params.append(int(tm))

    diet = (p.get('diet') or 'None')
    if diet in ('Veg','Vegan'):
        w.append('d.veg=1')

    spice = (p.get('spice_level') or 'Medium')
    if spice == 'Low':
        w.append("COALESCE(d.spice_level,'Medium') NOT IN ('High','Spicy')")
    elif spice == 'Medium':
        w.append("COALESCE(d.spice_level,'Medium') NOT IN ('Spicy')")

    avoid_tokens = []
    for src in (p.get('allergies') or '', p.get('avoid') or ''):
        r, o, x = normalize_tokens(src)
        avoid_tokens.extend([t for t in (r + o + x) if t])

    if avoid_tokens:
        placeholders = ','.join(['%s'] * len(avoid_tokens))
        w.append(
            f"d.id NOT IN (SELECT di.dish_id FROM dish_ingredients di "
            f"JOIN ingredients i ON i.id=di.ingredient_id "
            f"WHERE i.name IN ({placeholders}))"
        )
        params.extend(avoid_tokens)

    sql = (' AND ' + ' AND '.join(w)) if w else ''
    return sql, params


def ingredient_terms_from_text(s):
    s = (s or '').lower().strip()
    if not s: return []
    parts = re.split(r'[,\+\|\-\/]+', s)
    aliases = {
        'chkn':'chicken','chikn':'chicken','chk':'chicken','murghi':'chicken',
        'qeema':'keema','keema':'keema',
        'aloo':'potato','bhindi':'okra','saag':'spinach','machli':'fish',
        'dal':'dal','daal':'dal','dāl':'dal',
        'masoor':'masoor dal','moong':'moong dal','chanadal':'chana dal','chana':'chana dal',
        'mash':'urad dal','urad':'urad dal',
        'chawal':'rice','chāwal':'rice'
    }
    out=[]
    for p in parts:
        t=p.strip()
        if not t: continue
        if t.endswith('s') and len(t)>3: t=t[:-1]
        t=aliases.get(t,t)
        out.append(t)
    seen=set(); flat=[]
    for t in out:
        if t and t not in seen:
            flat.append(t); seen.add(t)
    return flat


if __name__ == '__main__':
    app.run(debug=True)
