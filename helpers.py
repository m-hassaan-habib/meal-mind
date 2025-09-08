from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
from datetime import date, timedelta, datetime
from db import query, execute
import uuid
from PIL import Image
import re
import requests
import random
from difflib import get_close_matches

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

    base = ('SELECT d.id,d.name,d.cuisine,d.time_min,d.image_url,ul.last_cooked_at,ul.created_at '
            'FROM user_library ul JOIN dishes d ON d.id=ul.dish_id '
            'WHERE ul.user_id=%s AND ul.active=1 AND d.id<>%s ')

    sql_cd = (base + 'AND d.id NOT IN (SELECT dish_id FROM day_plan WHERE user_id=%s AND date>=%s) ' + pf_sql +
              ' ORDER BY (ul.last_cooked_at IS NULL) DESC, '
              'COALESCE(ul.last_cooked_at, "1970-01-01") ASC, '
              'COALESCE(ul.created_at, "1970-01-01") DESC, '
              'RAND() LIMIT %s')
    rows = query(sql_cd, [user_id, exclude_id, user_id, today - timedelta(days=cd)] + pf_params + [limit*2])

    if len(rows) < limit:
        sql_loose = (base + pf_sql +
                     ' ORDER BY (ul.last_cooked_at IS NULL) DESC, '
                     'COALESCE(ul.last_cooked_at, "1970-01-01") ASC, '
                     'COALESCE(ul.created_at, "1970-01-01") DESC, '
                     'RAND() LIMIT %s')
        rows = query(sql_loose, [user_id, exclude_id] + pf_params + [limit*2])

    out, seen = [], set()
    for r in rows:
        if r['id'] in seen: 
            continue
        seen.add(r['id'])
        out.append({
            'id': r['id'],
            'name': r['name'],
            'cuisine': r['cuisine'],
            'time_min': r['time_min'] or 0,
            'image_url': r['image_url'],
            'is_web': 0
        })
        if len(out) == limit:
            break

    if len(out) < limit:
        for w in discover_candidates(user_id, limit - len(out)):
            out.append({
                'id': None,
                'name': w['name'],
                'cuisine': w.get('cuisine'),
                'time_min': w.get('time_min') or 0,
                'image_url': w.get('image_url'),
                'is_web': 1,
                'df_id': w['id']
            })
    return out


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


def week_start(d=None):
    d = d or date.today()
    return d - timedelta(days=d.weekday())


def library_candidates(user_id=1, limit=6):
    today = date.today()
    cd = get_cooldown_days(user_id)
    pf_sql, pf_params = pref_filter_sql(user_id)
    sql = ('SELECT d.id,d.name,d.cuisine,d.time_min,d.difficulty,d.veg,d.spice_level,d.image_url '
           'FROM user_library ul JOIN dishes d ON d.id=ul.dish_id '
           'WHERE ul.user_id=%s AND ul.active=1 AND d.id NOT IN '
           '(SELECT dish_id FROM day_plan WHERE user_id=%s AND date>=%s)') + pf_sql + ' ORDER BY RAND() LIMIT %s'
    return query(sql, [user_id, user_id, today - timedelta(days=cd)] + pf_params + [limit])


def pk_catalog_candidates(user_id=1, limit=6):
    pf_sql, pf_params = pref_filter_sql(user_id)
    sql = ('SELECT d.id,d.name,d.cuisine,d.time_min,d.difficulty,d.veg,d.spice_level,d.image_url '
           'FROM dishes d LEFT JOIN user_library ul ON ul.dish_id=d.id AND ul.user_id=%s '
           'WHERE d.cuisine=%s AND (ul.dish_id IS NULL OR ul.active=0)') + pf_sql + ' ORDER BY RAND() LIMIT %s'
    return query(sql, [user_id, 'Pakistani'] + pf_params + [limit])


def ensure_weekly_discover(user_id=1, total=8, lib_target=4, web_target=4):
    ws = week_start()
    have = query('SELECT COUNT(*) c FROM discover_feed WHERE user_id=%s AND week_start=%s', (user_id, ws), one=True)['c']
    if int(have or 0) >= total:
        return
    lib = library_candidates(user_id, lib_target)
    web = web_weekly_candidates(user_id, web_target)
    items, ids = [], set()
    for r in lib:
        if r['id'] in ids: 
            continue
        items.append(('library', r['id'], None)); ids.add(r['id'])
    for w in web:
        n = (w.get('name') or '').strip().lower()
        if n in ids: 
            continue
        items.append(('web', None, w)); ids.add(n)
    items = items[:total]
    execute('DELETE FROM discover_feed WHERE user_id=%s AND week_start=%s', (user_id, ws))
    rank = 1
    for src, did, w in items:
        if src == 'library':
            execute('INSERT INTO discover_feed (user_id,week_start,dish_id,source,sort_rank) VALUES (%s,%s,%s,%s,%s)', (user_id, ws, did, 'library', rank))
        else:
            execute('INSERT INTO discover_feed (user_id,week_start,source,sort_rank,name,image_url,source_url,time_min,cuisine,difficulty,veg) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (user_id, ws, 'web', rank, w.get('name'), w.get('image_url'), w.get('source_url',''), w.get('time_min'), w.get('cuisine'), w.get('difficulty'), int(w.get('veg',0))))
        rank += 1


def previously_seen_names(user_id=1):
    rows = query('SELECT LOWER(TRIM(COALESCE(name,""))) n FROM discover_feed WHERE user_id=%s AND name IS NOT NULL', (user_id,))
    return {r['n'] for r in rows}


def web_weekly_candidates(user_id=1, limit=12):
    lib_names = {(r['name'] or '').strip().lower() for r in query('SELECT d.name FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1', (user_id,))}
    ws = week_start()
    curr_names = {(r['name'] or '').strip().lower() for r in query('SELECT name FROM discover_feed WHERE user_id=%s AND week_start=%s AND source=%s', (user_id, ws, 'web'))}
    pool = web_area_list('Pakistani', 60) + web_area_list('Indian', 60)
    out, seen = [], set()
    random.shuffle(pool)
    for m in pool:
        n = (m.get('name') or '').strip().lower()
        if not n or n in lib_names or n in curr_names or n in seen:
            continue
        seen.add(n)
        out.append(m)
        if len(out) >= limit:
            break
    return out


def ensure_weekly_web_discover(user_id=1, total=12):
    ws = week_start()
    execute('DELETE FROM discover_feed WHERE user_id=%s AND week_start=%s AND source=%s', (user_id, ws, 'web'))
    items = web_weekly_candidates(user_id, total)
    rnk = 1
    for w in items:
        execute(
            'INSERT INTO discover_feed (user_id,week_start,source,sort_rank,name,image_url,source_url,time_min,cuisine,difficulty,veg) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (user_id, ws, 'web', rnk, w.get('name'), w.get('image_url'), w.get('source_url',''), w.get('time_min'), w.get('cuisine'), w.get('difficulty'), int(w.get('veg',0)))
        )
        rnk += 1


def ensure_web_dish_into_library(payload, user_id=1):
    name = (payload.get('name') or '').strip()
    if not name:
        return None
    row = query('SELECT id FROM dishes WHERE name=%s', (name,), one=True)
    if row:
        did = row['id']
        execute('INSERT IGNORE INTO user_library (user_id,dish_id) VALUES (%s,%s)', (user_id, did))
        if payload.get('image_url'):
            execute('UPDATE dishes SET image_url=CASE WHEN COALESCE(image_url,"")="" THEN %s ELSE image_url END WHERE id=%s', (payload.get('image_url'), did))
        return did
    time_min = int(payload.get('time_min') or 40)
    cuisine = payload.get('cuisine') or 'Pakistani'
    difficulty = payload.get('difficulty') or 'Medium'
    veg = int(payload.get('veg') or 0)
    spice = payload.get('spice_level') or 'Medium'
    image_url = payload.get('image_url') or '/static/img/placeholder.jpg'
    did = execute('INSERT INTO dishes (name,cuisine,time_min,difficulty,veg,spice_level,image_url) VALUES (%s,%s,%s,%s,%s,%s,%s)', (name,cuisine,time_min,difficulty,veg,spice,image_url))
    execute('INSERT IGNORE INTO user_library (user_id,dish_id) VALUES (%s,%s)', (user_id, did))
    return did


def ensure_materialized_feed(user_id=1):
    ws = week_start()
    rows = query('SELECT id,name,image_url,source_url,time_min,cuisine,difficulty,veg FROM discover_feed WHERE user_id=%s AND week_start=%s AND source=%s AND (dish_id IS NULL OR dish_id=0)', (user_id, ws, 'web'))
    for r in rows:
        did = ensure_web_dish_into_library(r, user_id)
        if did:
            execute('UPDATE discover_feed SET dish_id=%s WHERE id=%s', (did, r['id']))


def discover_candidates(user_id=1, limit=3):
    ws = week_start()
    rows = query(
        'SELECT id,name,image_url,source_url,time_min,cuisine,difficulty,veg '
        'FROM discover_feed WHERE user_id=%s AND week_start=%s AND source=%s '
        'AND (dish_id IS NULL OR dish_id=0) ORDER BY sort_rank ASC, id ASC LIMIT %s',
        (user_id, ws, 'web', limit)
    )
    return rows


def materialize_discover(df_id, user_id=1):
    r = query('SELECT id,name,image_url,source_url,time_min,cuisine,difficulty,veg FROM discover_feed WHERE id=%s AND user_id=%s', (df_id, user_id), one=True)
    if not r: return None
    did = ensure_web_dish_into_library(r, user_id)
    if did:
        execute('UPDATE discover_feed SET dish_id=%s WHERE id=%s', (did, df_id))
    return did


def days_ago(d):
    if not d:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return (date.today() - d).days


def web_area_list(area, limit=60):
    try:
        r = requests.get('https://www.themealdb.com/api/json/v1/1/filter.php', params={'a': area}, timeout=6)
        j = r.json() if r.status_code == 200 else {}
        meals = j.get('meals') or []
    except Exception:
        meals = []
    out = []
    for m in meals:
        out.append({
            'name': m.get('strMeal'),
            'image_url': m.get('strMealThumb'),
            'source_url': f"https://www.themealdb.com/meal/{m.get('idMeal')}",
            'time_min': 40,
            'cuisine': area,
            'difficulty': 'Medium',
            'veg': 0
        })
    random.shuffle(out)
    return out[:limit]
