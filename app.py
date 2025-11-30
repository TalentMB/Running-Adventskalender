from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
import datetime
from sqlalchemy import func
import os

# --- App Konfiguration ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///team_challenge.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'Ihr_geheimer_schluessel'  # Für Flash-Nachrichten benötigt
db = SQLAlchemy(app)


# --- Datenbank Modelle ---

# Modell für die Benutzer (Amelie, Lazo, etc.)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    # Zugehörige Farbe für die Visualisierung (Hex-Code)
    farbe = db.Column(db.String(7), nullable=False)


# Modell für die 24 Türchen (ID 1-24)
class Tuerchen(db.Model):
    id = db.Column(db.Integer, primary_key=True)  # ID ist auch der Ziel-KM-Wert
    # Läufe, die zu diesem Türchen gehören
    laeufe = db.relationship('SharedLauf', backref='tuerchen', lazy=True)


# Modell für jeden einzelnen erfassten Lauf eines Benutzers
class SharedLauf(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kilometer = db.Column(db.Float, nullable=False)
    datum = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    tuerchen_id = db.Column(db.Integer, db.ForeignKey('tuerchen.id'), nullable=False)
    user = db.relationship('User', backref='shared_laeufe')


# --- Datenbank Initialisierung ---
def init_db():
    with app.app_context():
        db.create_all()

        # Benutzer werden NICHT mehr vordefiniert, sondern über das Frontend-Formular hinzugefügt.

        # Türchen anlegen (ID 1-24), falls nicht vorhanden
        if Tuerchen.query.count() == 0:
            for i in range(1, 25):
                t = Tuerchen(id=i)
                db.session.add(t)
            db.session.commit()


init_db()


# --- Backend Routen (Logik) ---

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST' and 'neuer_nutzer_name' in request.form:
        name = request.form['neuer_nutzer_name']
        if User.query.filter_by(name=name).first():
            flash("Name existiert bereits.", "error")
        elif User.query.count() >= 3:
            flash("Maximale Teamgröße (3 Personen) erreicht.", "error")
        else:
            # Farben dynamisch zuweisen (Hex-Codes für bessere Kompatibilität)
            if User.query.count() == 0:
                farbe = '#007bff'  # Blau
            elif User.query.count() == 1:
                farbe = '#28a745'  # Grün
            else:
                farbe = '#ff9800'  # Orange

            neuer_user = User(name=name, farbe=farbe)
            db.session.add(neuer_user)
            db.session.commit()
            flash(f"Nutzer {name} hinzugefügt.", "success")
        return redirect(url_for('index'))

    alle_tuerchen = Tuerchen.query.order_by(Tuerchen.id).all()
    gesamt_ziel = sum(tuer.id for tuer in alle_tuerchen)
    gesamt_gelaufen = db.session.query(db.func.sum(SharedLauf.kilometer)).scalar() or 0
    users = User.query.all()

    tuer_daten = []
    for tuer in alle_tuerchen:
        km_erreicht = db.session.query(db.func.sum(SharedLauf.kilometer)).filter_by(tuerchen_id=tuer.id).scalar() or 0
        ziel_erreicht = km_erreicht >= tuer.id

        beitraege = []
        for user in users:
            user_km = db.session.query(db.func.sum(SharedLauf.kilometer)).filter_by(tuerchen_id=tuer.id,
                                                                                    user_id=user.id).scalar() or 0
            if km_erreicht > 0:
                prozent = (user_km / km_erreicht) * 100
                if prozent > 0:
                    beitraege.append({'user_name': user.name, 'km': user_km, 'prozent': prozent, 'farbe': user.farbe})

        tuer_daten.append({
            'id': tuer.id,
            'ziel_km': tuer.id,
            'erreicht_km': km_erreicht,
            'ist_erledigt': ziel_erreicht,
            'beitraege': beitraege
        })

    return render_template('index.html',
                           tuer_liste=tuer_daten,
                           gesamt_ziel=gesamt_ziel,
                           gesamt_gelaufen=gesamt_gelaufen,
                           users=users)


@app.route('/lauf_erfassen_formular/<int:tuer_id>', methods=['GET'])
def lauf_erfassen_formular(tuer_id):
    tuer = Tuerchen.query.get_or_404(tuer_id)
    users = User.query.all()
    km_erreicht = db.session.query(db.func.sum(SharedLauf.kilometer)).filter_by(tuerchen_id=tuer.id).scalar() or 0
    verbleibende_km = max(0, tuer.id - km_erreicht)

    if verbleibende_km == 0:
        flash(f"Türchen {tuer_id} ist bereits voll gelaufen!", "error")
        return redirect(url_for('index'))

    return render_template('lauf_erfassen.html',
                           tuer=tuer,
                           users=users,
                           verbleibende_km=verbleibende_km,
                           km_erreicht=km_erreicht)


@app.route('/lauf_eintragen', methods=['POST'])
def lauf_eintragen():
    user_id = request.form.get('user_id')
    tuer_id = request.form.get('tuer_id')
    try:
        kilometer = float(request.form.get('kilometer'))
    except (ValueError, TypeError):
        flash("Ungültige Kilometer-Angabe.", "error")
        return redirect(url_for('lauf_erfassen_formular', tuer_id=tuer_id))

    km_erreicht = db.session.query(db.func.sum(SharedLauf.kilometer)).filter_by(tuerchen_id=tuer_id).scalar() or 0
    ziel_km = Tuerchen.query.get(tuer_id).id

    if km_erreicht + kilometer > ziel_km:
        flash(f"Fehler: Es können nur noch maximal {ziel_km - km_erreicht:.1f} km eingetragen werden.", "error")
        return redirect(url_for('lauf_erfassen_formular', tuer_id=tuer_id))

    if user_id and tuer_id and kilometer > 0:
        neuer_lauf = SharedLauf(kilometer=kilometer, user_id=user_id, tuerchen_id=tuer_id)
        db.session.add(neuer_lauf)
        db.session.commit()
        flash("Lauf erfolgreich eingetragen!", "success")
    else:
        flash("Fehler beim Eintragen des Laufs.", "error")

    return redirect(url_for('index'))


@app.route('/tuer_zuruecksetzen/<int:tuer_id>', methods=['POST'])
def tuer_zuruecksetzen(tuer_id):
    # Diese Funktion löscht ALLE Läufe, die diesem Türchen zugeordnet sind
    with app.app_context():
        laeufe_zum_loeschen = SharedLauf.query.filter_by(tuerchen_id=tuer_id).all()
        for lauf in laeufe_zum_loeschen:
            db.session.delete(lauf)
        db.session.commit()
        flash(f"Alle Läufe für Türchen {tuer_id} wurden zurückgesetzt.", "success")

    return redirect(url_for('index'))


# --- App Start ---
if __name__ == '__main__':
    app.run(debug=True)
