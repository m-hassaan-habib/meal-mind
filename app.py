from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
from datetime import date, timedelta, datetime
import csv, io
import config
from db import close_db, query, execute
import os
from difflib import get_close_matches
from helpers import *

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'static', 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.teardown_appcontext(close_db)


@app.context_processor
def url_helpers():
    def url_for_history(**kwargs):
        args = dict(request.args)
        args.update(kwargs)
        return url_for('history', **args)
    return dict(url_for_history=url_for_history)


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
    next_url = request.form.get('next') or url_for('today')
    today_d = date.today()
    exist = query('SELECT id FROM day_plan WHERE user_id=%s AND date=%s', (1, today_d), one=True)
    if not exist:
        execute('INSERT INTO day_plan (user_id,date,dish_id,is_override) VALUES (%s,%s,%s,0)', (1, today_d, dish_id))
    else:
        execute('UPDATE day_plan SET dish_id=%s,is_override=0 WHERE id=%s', (dish_id, exist['id']))
    execute('UPDATE user_library SET last_cooked_at=%s WHERE user_id=%s AND dish_id=%s', (today_d, 1, dish_id))
    return redirect(next_url)


@app.post('/swap')
def swap():
    dish_id = int(request.form['dish_id'])
    alts = alt_picks(dish_id, 1, 3)
    return jsonify(alts)


@app.get('/override')
def override_get():
    return render_template('override.html')


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
    ensure_weekly_web_discover(1, total=12)
    ws = week_start()
    rows = query('SELECT id,name,image_url,source_url,time_min,cuisine,difficulty,veg FROM discover_feed WHERE user_id=%s AND week_start=%s AND source=%s ORDER BY sort_rank ASC, id ASC', (1, ws, 'web'))
    picks = [{'source':'web','df_id':r['id'],'name':r['name'],'image_url':r['image_url'],'source_url':r['source_url'],'time_min':r['time_min'],'cuisine':r['cuisine'],'difficulty':r['difficulty'],'veg':r['veg']} for r in rows]
    return render_template('discover.html', picks=picks, weekly=True)


@app.post('/discover/regen')
def discover_regen():
    ensure_weekly_web_discover(1)
    return redirect(url_for('discover'))


def discover_candidates(user_id=1, limit=3):
    ws = week_start()
    return query('SELECT id,name,image_url,time_min,cuisine FROM discover_feed WHERE user_id=%s AND week_start=%s AND source=%s ORDER BY RAND() LIMIT %s', (user_id, ws, 'web', limit))


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


@app.post('/discover/import_cook')
def discover_import_cook():
    df_id = int(request.form['df_id'])
    did = materialize_discover(df_id, 1)
    if did:
        today_d = date.today()
        exist = query('SELECT id FROM day_plan WHERE user_id=%s AND date=%s', (1, today_d), one=True)
        if not exist:
            execute('INSERT INTO day_plan (user_id,date,dish_id,is_override) VALUES (%s,%s,%s,1)', (1, today_d, did))
        else:
            execute('UPDATE day_plan SET dish_id=%s,is_override=1 WHERE id=%s', (did, exist['id']))
        execute('UPDATE user_library SET last_cooked_at=%s WHERE user_id=%s AND dish_id=%s', (today_d, 1, did))
    return redirect(url_for('today'))


@app.context_processor
def inject_days_ago():
    return dict(days_ago=days_ago)


if __name__ == '__main__':
    app.run(debug=True)
