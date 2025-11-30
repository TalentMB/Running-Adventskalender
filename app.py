from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from flask_sqlalchemy import SQLAlchemy
import datetime
from sqlalchemy import func
import os
from werkzeug.security import generate_password_hash, check_password_hash

# --- App Konfiguration ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///multi_team_challenge.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'Ihr_geheimer_schluessel'

# Session Konfiguration (standardmäßig nach Browser-Schluss gelöscht)
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=False)
db = SQLAlchemy(app)


# --- Datenbank Modelle ---

class Team(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    pin_code_hash = db.Column(db.String(128), nullable=True)
    users = db.relationship('User', backref='team', lazy=True)
    tuerchen_liste = db.relationship('Tuerchen', backref='team', lazy=True)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    farbe = db.Column(db.String(7), nullable=False)  # Speichert den HEX-Code
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)


class Tuerchen(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tuer_nummer = db.Column(db.Integer, nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('team.id'), nullable=False)
    laeufe = db.relationship('SharedLauf', backref='tuerchen', lazy=True)


class SharedLauf(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kilometer = db.Column(db.Float, nullable=False)
    datum = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tuerchen_id = db.Column(db.Integer, db.ForeignKey('tuerchen.id'), nullable=False)


# --- Datenbank Initialisierung ---
def init_db():
    with app.app_context():
        db.create_all()


def setup_team_tuerchen(team_id):
    with app.app_context():
        if Tuerchen.query.filter_by(team_id=team_id).count() == 0:
            for i in range(1, 25):
                t = Tuerchen(tuer_nummer=i, team_id=team_id)
                db.session.add(t)
            db.session.commit()


init_db()


# --- Backend Routen (Logik) ---

@app.route('/logout')
def logout():
    session.pop('team_id', None)
    session.pop('can_write', None)
    flash("Team erfolgreich gewechselt.", "success")
    return redirect(url_for('team_login'))


@app.route('/team', methods=['GET', 'POST'])
def team_login():
    if request.method == 'POST':
        team_name = request.form.get('team_name')
        pin_code_eingabe = request.form.get('pin_code')
        action = request.form.get('action')

        if not team_name:
            flash("Teamname benötigt.", "error")
            return redirect(url_for('team_login'))

        team = Team.query.filter_by(name=team_name).first()

        if team:
            if action == 'join':
                if team.pin_code_hash and check_password_hash(team.pin_code_hash, pin_code_eingabe):
                    session['team_id'] = team.id
                    session['can_write'] = True
                    flash(f"Willkommen zurück bei Team {team_name}!", "success")
                else:
                    flash("Falscher PIN-Code oder PIN benötigt, um beizutreten.", "error")
                    return redirect(url_for('team_login'))
            elif action == 'view':
                session['team_id'] = team.id
                session['can_write'] = False
                flash(f"Sie besuchen Team {team_name} (Nur Lesezugriff).", "success")

        else:
            if action != 'join' or not pin_code_eingabe or len(pin_code_eingabe) != 4:
                flash("Für ein neues Team wird ein 4-stelliger PIN und die Aktion 'Beitreten' benötigt.", "error")
                return redirect(url_for('team_login'))

            hashed_pin = generate_password_hash(pin_code_eingabe)
            neues_team = Team(name=team_name, pin_code_hash=hashed_pin)
            db.session.add(neues_team)
            db.session.commit()
            session['team_id'] = neues_team.id
            session['can_write'] = True
            setup_team_tuerchen(neues_team.id)
            flash(f"Neues Team {team_name} erstellt. PIN: {pin_code_eingabe}", "success")

        return redirect(url_for('index'))

    existing_teams = Team.query.all()
    return render_template('team_login.html', existing_teams=existing_teams)


@app.route('/')
def index():
    team_id = session.get('team_id')
    if not team_id: return redirect(url_for('team_login'))
    team = Team.query.get(team_id)
    if not team:
        session.pop('team_id', None);
        session.pop('can_write', None)
        flash("Ihr Team existiert nicht mehr.", "error")
        return redirect(url_for('team_login'))

    can_write = session.get('can_write', False)

    alle_tuerchen = Tuerchen.query.filter_by(team_id=team_id).order_by(Tuerchen.tuer_nummer).all()
    gesamt_ziel = sum(tuer.tuer_nummer for tuer in alle_tuerchen)
    gesamt_gelaufen = db.session.query(db.func.sum(SharedLauf.kilometer)).filter(
        SharedLauf.tuerchen.has(team_id=team_id)).scalar() or 0
    users = User.query.filter_by(team_id=team_id).all()

    tuer_daten = []
    for tuer in alle_tuerchen:
        km_erreicht = db.session.query(db.func.sum(SharedLauf.kilometer)).filter_by(tuerchen_id=tuer.id).scalar() or 0
        ziel_erreicht = km_erreicht >= tuer.tuer_nummer

        beitraege = []
        for user in users:
            user_km = db.session.query(db.func.sum(SharedLauf.kilometer)).filter_by(tuerchen_id=tuer.id,
                                                                                    user_id=user.id).scalar() or 0
            if km_erreicht > 0:
                prozent = (user_km / km_erreicht) * 100
                if prozent > 0:
                    # Füge 'farbe' zum Dictionary hinzu
                    beitraege.append({'user_name': user.name, 'km': user_km, 'prozent': prozent, 'farbe': user.farbe})

        tuer_daten.append({
            'id': tuer.id,
            'tuer_nummer': tuer.tuer_nummer,
            'ziel_km': tuer.tuer_nummer,
            'erreicht_km': km_erreicht,
            'ist_erledigt': ziel_erreicht,
            'beitraege': beitraege
        })

    return render_template('index.html',
                           tuer_liste=tuer_daten,
                           gesamt_ziel=gesamt_ziel,
                           gesamt_gelaufen=gesamt_gelaufen,
                           users=users,
                           team_name=team.name,
                           can_write=can_write)


@app.route('/add_user', methods=['POST'])
def add_user():
    if not session.get('can_write'): abort(403)
    team_id = session.get('team_id')
    if not team_id: return redirect(url_for('team_login'))

    name = request.form['neuer_nutzer_name']
    if User.query.filter_by(name=name, team_id=team_id).first():
        flash("Name existiert bereits in diesem Team.", "error")
    elif User.query.filter_by(team_id=team_id).count() >= 3:
        flash("Maximale Teamgröße (3 Personen) erreicht.", "error")
    else:
        # LOGIK FÜR DIE NEUEN FARBEN (Blau, Schwarz, Rot)
        user_count = User.query.filter_by(team_id=team_id).count()
        if user_count == 0:
            farbe = '#0000FF' # 1. Person: Blau
        elif user_count == 1:
            farbe = '#000000' # 2. Person: Schwarz
        else:
            farbe = '#FF0000' # 3. Person: Rot (statt Pink)

        neuer_user = User(name=name, farbe=farbe, team_id=team_id)
        db.session.add(neuer_user)
        db.session.commit()
        flash(f"Nutzer {name} zu Team {Team.query.get(team_id).name} hinzugefügt.", "success")

    return redirect(url_for('index'))


@app.route('/lauf_erfassen_formular/<int:tuer_db_id>', methods=['GET'])
def lauf_erfassen_formular(tuer_db_id):
    if not session.get('can_write'): abort(403)
    team_id = session.get('team_id')
    if not team_id: return redirect(url_for('team_login'))

    tuer = Tuerchen.query.get_or_404(tuer_db_id)
    if tuer.team_id != team_id: abort(403)

    users = User.query.filter_by(team_id=team_id).all()
    km_erreicht = db.session.query(db.func.sum(SharedLauf.kilometer)).filter_by(tuerchen_id=tuer_db_id).scalar() or 0
    verbleibende_km = max(0, tuer.tuer_nummer - km_erreicht)

    if verbleibende_km == 0:
        flash(f"Türchen {tuer.tuer_nummer} ist bereits voll gelaufen!", "error")
        return redirect(url_for('index'))

    return render_template('lauf_erfassen.html',
                           tuer=tuer,
                           users=users,
                           verbleibende_km=verbleibende_km,
                           km_erreicht=km_erreicht)


@app.route('/lauf_eintragen', methods=['POST'])
def lauf_eintragen():
    if not session.get('can_write'): abort(403)
    team_id = session.get('team_id')
    if not team_id: return redirect(url_for('team_login'))

    user_id = request.form.get('user_id')
    tuer_db_id = request.form.get('tuer_id')

    try:
        kilometer = float(request.form.get('kilometer'))
    except (ValueError, TypeError):
        flash("Ungültige Kilometer-Angabe.", "error")
        return redirect(url_for('lauf_erfassen_formular', tuer_db_id=tuer_db_id))

    km_erreicht = db.session.query(db.func.sum(SharedLauf.kilometer)).filter_by(tuerchen_id=tuer_db_id).scalar() or 0
    ziel_km = Tuerchen.query.get(tuer_db_id).tuer_nummer

    if km_erreicht + kilometer > ziel_km:
        flash(f"Fehler: Es können nur noch maximal {ziel_km - km_erreicht:.1f} km eingetragen werden.", "error")
        return redirect(url_for('lauf_erfassen_formular', tuer_db_id=tuer_db_id))

    if user_id and tuer_db_id and kilometer > 0:
        neuer_lauf = SharedLauf(kilometer=kilometer, user_id=user_id, tuerchen_id=tuer_db_id)
        db.session.add(neuer_lauf)
        db.session.commit()
        flash("Lauf erfolgreich eingetragen!", "success")
    else:
        flash("Fehler beim Eintragen des Laufs.", "error")

    return redirect(url_for('index'))


@app.route('/tuer_zuruecksetzen/<int:tuer_db_id>', methods=['POST'])
def tuer_zuruecksetzen(tuer_db_id):
    if not session.get('can_write'): abort(403)
    team_id = session.get('team_id')
    if not team_id: return redirect(url_for('team_login'))

    tuer = Tuerchen.query.get_or_404(tuer_db_id)
    if tuer.team_id != team_id: abort(403)

    with app.app_context():
        SharedLauf.query.filter_by(tuerchen_id=tuer_db_id).delete()
        db.session.commit()
        flash(f"Alle Läufe für dieses Türchen wurden zurückgesetzt.", "success")

    return redirect(url_for('index'))


# --- App Start ---
if __name__ == '__main__':
    app.run(debug=True)
