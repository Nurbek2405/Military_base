import os
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///default.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
db = SQLAlchemy(app)

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

class Person(db.Model):
    __tablename__ = 'persons'
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, unique=True, nullable=False)
    fio = db.Column(db.String(100), nullable=False)
    birth_date = db.Column(db.DateTime, nullable=True)
    checks = db.relationship('MedicalCheck', backref='person', lazy=True)

class MedicalCheck(db.Model):
    __tablename__ = 'medical_checks'
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey('persons.id'), nullable=False)
    check_date = db.Column(db.DateTime, nullable=False)
    check_type = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(20), nullable=True)
    disease = db.Column(db.String(200), nullable=True)
    risk = db.Column(db.String(100), nullable=True)
    photo_path = db.Column(db.String(200), nullable=True)

    def get_expiry_date(self):
        if self.check_type == "3m":
            return self.check_date + timedelta(days=90)
        elif self.check_type in ["1y", "vlek"]:
            return self.check_date + timedelta(days=365)
        return self.check_date

with app.app_context():
    db.create_all()
    if Person.query.count() > 0:
        max_number = db.session.query(db.func.max(Person.number)).scalar() or 0
    else:
        max_number = 0
    Person.next_number = max_number + 1

@app.route('/', methods=['GET'])
def index():
    sort_by = request.args.get('sort', 'expiry')
    search_query = request.args.get('search', '').strip()

    if search_query:
        people = Person.query.filter(Person.fio.ilike(f'%{search_query}%')).all()
    else:
        people = Person.query.all()

    if sort_by == 'expiry':
        people = sorted(people, key=lambda p: p.checks[-1].get_expiry_date() if p.checks else datetime.max)
    elif sort_by == 'fio':
        people = sorted(people, key=lambda p: p.fio)
    elif sort_by == 'number':
        people = sorted(people, key=lambda p: p.number)

    current_date = datetime.now()
    return render_template('index.html', people=people, current_date=current_date, search_query=search_query)

@app.route('/add', methods=['GET', 'POST'])
def add_person():
    if request.method == 'POST':
        fio = request.form['fio']
        birth_date = datetime.strptime(request.form['birth_date'], '%Y-%m-%d') if request.form['birth_date'] else None
        check_date = datetime.strptime(request.form['check_date'], '%Y-%m-%d')
        check_type = request.form['check_type']
        status = request.form['status']
        disease = request.form['disease']
        risk = request.form['risk']
        photo = request.files.get('photo')

        photo_path = None
        if photo and photo.filename:
            filename = photo.filename
            photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            photo.save(photo_path)

        person = Person(number=Person.next_number, fio=fio, birth_date=birth_date)
        Person.next_number += 1
        db.session.add(person)
        db.session.commit()

        new_check = MedicalCheck(person_id=person.id, check_date=check_date, check_type=check_type,
                                status=status, disease=disease, risk=risk, photo_path=photo_path)
        db.session.add(new_check)
        db.session.commit()
        flash('Летчик добавлен')
        return redirect(url_for('index'))
    return render_template('add.html')

@app.route('/edit/<int:person_id>', methods=['GET', 'POST'])
def edit_person(person_id):
    person = Person.query.get_or_404(person_id)
    if request.method == 'POST':
        if 'add_check' in request.form:
            check_date = datetime.strptime(request.form['check_date'], '%Y-%m-%d')
            check_type = request.form['check_type']
            status = request.form['status']
            disease = request.form['disease']
            risk = request.form['risk']
            photo = request.files.get('photo')

            photo_path = None
            if photo and photo.filename:
                filename = photo.filename
                photo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                photo.save(photo_path)

            new_check = MedicalCheck(person_id=person.id, check_date=check_date, check_type=check_type,
                                    status=status, disease=disease, risk=risk, photo_path=photo_path)
            db.session.add(new_check)
            db.session.commit()
            flash('Осмотр добавлен')
        return redirect(url_for('edit_person', person_id=person_id))
    return render_template('edit.html', person=person)

@app.route('/delete/<int:person_id>')
def delete_person(person_id):
    person = Person.query.get_or_404(person_id)
    for check in person.checks:
        if check.photo_path and os.path.exists(check.photo_path):
            os.remove(check.photo_path)
        db.session.delete(check)
    db.session.delete(person)
    db.session.commit()
    flash('Летчик удален')
    return redirect(url_for('index'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)