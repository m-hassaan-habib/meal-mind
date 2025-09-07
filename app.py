from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
from datetime import date, timedelta, datetime
import csv, io, random
import config
from db import close_db, query, execute

app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.teardown_appcontext(close_db)

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
    rows = query('SELECT d.*, ul.last_cooked_at FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1 AND d.id NOT IN (SELECT dish_id FROM day_plan WHERE user_id=%s AND date >= %s)', (user_id, user_id, today - timedelta(days=cd)))
    if not rows:
        rows = query('SELECT d.*, ul.last_cooked_at FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1', (user_id,))
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
    rows = query('SELECT d.*, ul.last_cooked_at FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1 AND d.id<>%s AND d.id NOT IN (SELECT dish_id FROM day_plan WHERE user_id=%s AND date>=%s)', (user_id, exclude_id, user_id, today - timedelta(days=cd)))
    if not rows:
        rows = query('SELECT d.*, ul.last_cooked_at FROM user_library ul JOIN dishes d ON d.id=ul.dish_id WHERE ul.user_id=%s AND ul.active=1 AND d.id<>%s', (user_id, exclude_id))
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
    t = s.replace('+', ' ').replace(',', ' ').lower().split()
    return [x.strip() for x in t if x.strip()]

def match_dishes(tokens):
    if not tokens:
        return []
    placeholders = ','.join(['%s']*len(tokens))
    rows = query(f"""SELECT d.id,d.name,d.cuisine,d.time_min,d.difficulty,d.veg,d.spice_level,SUM(CASE WHEN i.name IN ({placeholders}) THEN 1 ELSE 0 END) AS hit,COUNT(di.ingredient_id) AS total FROM dishes d LEFT JOIN dish_ingredients di ON di.dish_id=d.id LEFT JOIN ingredients i ON i.id=di.ingredient_id GROUP BY d.id ORDER BY hit DESC, total ASC, d.time_min ASC LIMIT 5""", tokens)
    return [r for r in rows if r['hit']>0]

@app.post('/override')
def override_post():
    raw = request.form.get('ingredients','')
    tokens = normalize_tokens(raw)
    matches = match_dishes(tokens)
    return render_template('override_results.html', raw=raw, tokens=tokens, matches=matches)

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
    img = '/static/img/placeholder.jpg'
    row = query('SELECT id FROM dishes WHERE name=%s', (name,), one=True)
    if not row:
        dish_id = execute('INSERT INTO dishes (name,cuisine,time_min,difficulty,veg,spice_level,image_url) VALUES (%s,%s,%s,%s,%s,%s,%s)', (name,cuisine,time_min,difficulty,veg,spice,img))
    else:
        dish_id = row['id']
    execute('INSERT IGNORE INTO user_library (user_id,dish_id) VALUES (%s,%s)', (1,dish_id))
    toks = normalize_tokens(ingredients)
    for t in toks:
        ing = query('SELECT id FROM ingredients WHERE name=%s', (t,), one=True)
        if not ing:
            iid = execute('INSERT INTO ingredients (name) VALUES (%s)', (t,))
        else:
            iid = ing['id']
        execute('INSERT IGNORE INTO dish_ingredients (dish_id,ingredient_id) VALUES (%s,%s)', (dish_id,iid))
    return redirect(url_for('library'))

@app.get('/history')
def history():
    rows = query('SELECT d.*, dp.date AS cooked_date, dp.is_override FROM day_plan dp JOIN dishes d ON d.id=dp.dish_id WHERE dp.user_id=%s ORDER BY dp.date DESC LIMIT 60', (1,))
    return render_template('history.html', rows=rows)

@app.get('/discover')
def discover():
    picks = query('SELECT id,name,cuisine,time_min,difficulty,veg,spice_level,image_url FROM dishes ORDER BY RAND() LIMIT 6')
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

if __name__ == '__main__':
    app.run(debug=True)
